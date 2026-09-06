#!/usr/bin/env bash
# Setup Solar transport gateway (no listener reuse).
#
# Usage:
#   bash .../setup_transport_gateway.sh [--prepare-only] [--restart]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

ROOT_ENV_FILE="$SOLAR_WORKSPACE/.env"
RUN_DIR="$(gateway_run_dir)"
mkdir -p "$RUN_DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

resolve_bin() {
  local name="$1"
  shift || true
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
    return 0
  fi
  local candidate
  for candidate in "$@"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

usage() {
  cat <<EOF
Usage:
  bash $(transport_gateway_script setup_transport_gateway.sh) [--prepare-only] [--restart]

Default behavior:
1) Prepare env + dependencies
2) Start websocket bridge (fail if port busy without --restart)
3) Start http webhook bridge
4) Start cloudflared tunnel (quick or named based on SOLAR_TUNNEL_MODE)
5) Auto-detect public URL
6) Register + verify Telegram webhook
7) Write env.stamp on success

Options:
  --prepare-only   Run prepare steps only (no long-running services/tunnel)
  --restart        Stop owned runtime (after preflight) then start fresh
EOF
}

PREPARE_ONLY=false
RESTART=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --restart) RESTART=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

UV_BIN="$(resolve_bin uv /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv")" || {
  echo "Missing dependency: uv"
  exit 1
}
CURL_BIN="$(resolve_bin curl /usr/bin/curl /usr/local/bin/curl)" || {
  echo "Missing dependency: curl"
  exit 1
}

bash "$(transport_gateway_script onboard_websocket_env.sh)"
"$UV_BIN" run --with websockets==12.0 python3 -c "import websockets" >/dev/null
bash "$(transport_gateway_script validate_websocket_bridge.sh)"

if [[ "$PREPARE_ONLY" == true ]]; then
  echo "Prepare-only completed."
  exit 0
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Missing dependency: cloudflared"
  echo "Install cloudflared and rerun:"
  echo "  macOS (Homebrew):"
  echo "    brew install cloudflared"
  echo "  Ubuntu/Debian:"
  echo "    sudo apt-get update && sudo apt-get install -y cloudflared"
  echo "  Verify:"
  echo "    cloudflared --version"
  echo "Or rerun with --prepare-only."
  exit 1
fi

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

# Refresh after .env reload
RUN_DIR="$(gateway_run_dir)"
mkdir -p "$RUN_DIR"
ws_port="$(gateway_ws_port)"
http_port="$(gateway_http_port)"

# Acquire gateway lock for any path that starts services / writes stamp.
if ! gateway_acquire_lock; then
  echo "Another gateway operation is in progress." >&2
  exit 0
fi
gateway_install_lock_trap

rollback_stop() {
  echo "⚠️  Setup failed — rolling back with stop..." >&2
  bash "$(transport_gateway_script stop_transport_gateway.sh)" || true
  gateway_write_env_fail "setup_failed"
}

# Ports occupied without --restart → error (no reuse).
ports_busy=false
if ! gateway_port_is_free "$ws_port"; then ports_busy=true; fi
if ! gateway_port_is_free "$http_port"; then ports_busy=true; fi

needs_stop=false
if [[ "$RESTART" == true ]]; then
  needs_stop=true
elif [[ "$ports_busy" == true ]]; then
  echo "❌ Port(s) occupied. Refusing to reuse listeners." >&2
  echo "   WS=$ws_port HTTP=$http_port" >&2
  echo "   Rerun with --restart to stop owned processes and start fresh." >&2
  exit 1
fi

# Preflight before destroying a healthy runtime, and before any cold start.
if ! gateway_preflight; then
  if gateway_runtime_healthy_local || [[ "$needs_stop" == true ]] || [[ "$RESTART" == true ]]; then
    echo "❌ Preflight failed — leaving current runtime untouched." >&2
  else
    echo "❌ Preflight failed — not starting." >&2
  fi
  gateway_write_env_fail "preflight_failed"
  exit 1
fi

if [[ "$needs_stop" == true ]]; then
  if ! bash "$(transport_gateway_script stop_transport_gateway.sh)"; then
    echo "❌ stop_transport_gateway failed; refusing to start." >&2
    gateway_write_env_fail "stop_failed"
    exit 1
  fi
  # Re-check free after stop
  if ! gateway_port_is_free "$ws_port" || ! gateway_port_is_free "$http_port"; then
    echo "❌ Ports still busy after stop. Use stop --force if foreign." >&2
    gateway_write_env_fail "ports_busy_after_stop"
    exit 1
  fi
fi

# --- Start bridges (never reuse) ---
nohup bash "$(transport_gateway_script run_websocket_bridge.sh)" \
  >"$RUN_DIR/ws.log" 2>&1 &
echo $! >"$RUN_DIR/ws.pid"

nohup bash "$(transport_gateway_script run_http_webhook_bridge.sh)" \
  >"$RUN_DIR/http.log" 2>&1 &
echo $! >"$RUN_DIR/http.pid"

sleep 1
actual_ws_pid="$(gateway_listener_pid_for_port "$ws_port" || true)"
actual_http_pid="$(gateway_listener_pid_for_port "$http_port" || true)"
if [[ -z "$actual_ws_pid" || -z "$actual_http_pid" ]]; then
  echo "Failed to start or detect local bridge listeners."
  echo "WS port ${ws_port} pid: ${actual_ws_pid:-missing}"
  echo "HTTP port ${http_port} pid: ${actual_http_pid:-missing}"
  echo "Check logs: $RUN_DIR/{ws.log,http.log}"
  rollback_stop
  exit 1
fi
echo "$actual_ws_pid" >"$RUN_DIR/ws.pid"
echo "$actual_http_pid" >"$RUN_DIR/http.pid"

host="${SOLAR_HTTP_HOST:-127.0.0.1}"
port="${SOLAR_HTTP_PORT:-8787}"
tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
if [[ "$tunnel_mode" == "named" ]]; then
  tunnel_name="${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}"
  tunnel_config="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
  tunnel_hostname="${SOLAR_CLOUDFLARED_HOSTNAME:-REPLACE_ME}"
  if [[ ! -f "$tunnel_config" ]]; then
    echo "Missing named tunnel config: $tunnel_config"
    echo "Run: bash $(transport_gateway_script configure_named_tunnel.sh)"
    rollback_stop
    exit 1
  fi
  nohup cloudflared tunnel --config "$tunnel_config" run "$tunnel_name" \
    >"$RUN_DIR/cloudflared.log" 2>&1 &
  echo $! >"$RUN_DIR/cloudflared.pid"
else
  nohup cloudflared tunnel --url "http://${host}:${port}" \
    >"$RUN_DIR/cloudflared.log" 2>&1 &
  echo $! >"$RUN_DIR/cloudflared.pid"
fi

detect_public_url() {
  local log_file="$1"
  grep -Eo 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$log_file" | tail -n1 || true
}

public_url=""
if [[ "$tunnel_mode" == "named" ]]; then
  tunnel_hostname="${SOLAR_CLOUDFLARED_HOSTNAME:-REPLACE_ME}"
  if [[ "$tunnel_hostname" == "REPLACE_ME" || -z "$tunnel_hostname" ]]; then
    echo "Missing SOLAR_CLOUDFLARED_HOSTNAME for named tunnel mode."
    rollback_stop
    exit 1
  fi
  public_url="https://${tunnel_hostname}"
else
  for _ in $(seq 1 30); do
    if [[ -f "$RUN_DIR/cloudflared.log" ]]; then
      public_url="$(detect_public_url "$RUN_DIR/cloudflared.log")"
    fi
    if [[ -n "$public_url" ]]; then
      break
    fi
    sleep 1
  done
fi

if [[ -z "$public_url" ]]; then
  echo "Could not detect cloudflared public URL automatically."
  echo "Check log: $RUN_DIR/cloudflared.log"
  rollback_stop
  exit 1
fi

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  set +e
  gateway_telegram_lifecycle_setup
  tg_set_code=$?
  set -e
  if [[ "$tg_set_code" -ne 0 ]]; then
    echo "❌ Telegram webhook set/verify failed — rolling back." >&2
    rollback_stop
    exit 1
  fi
fi

gateway_write_stamp

echo "Transport gateway setup completed."
echo "Public URL: $public_url"
echo "http_channels=$(gateway_http_channels_label)"
echo "telegram_claim=$(gateway_telegram_claim_label)"
echo "Processes:"
echo "  ws pid: $(cat "$RUN_DIR/ws.pid")"
echo "  http pid: $(cat "$RUN_DIR/http.pid")"
echo "  tunnel pid: $(cat "$RUN_DIR/cloudflared.pid")"
echo "Logs: $RUN_DIR/{ws.log,http.log,cloudflared.log}"
echo "Stamp: $(gateway_stamp_path)"
