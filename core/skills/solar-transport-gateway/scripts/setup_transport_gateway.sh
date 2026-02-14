#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
RUN_DIR="${SOLAR_GATEWAY_RUN_DIR:-/tmp/solar-transport-gateway}"
mkdir -p "$RUN_DIR"

# LaunchAgent jobs run with a minimal PATH. Add common Homebrew locations so
# dependencies installed by brew (poetry/cloudflared) are resolvable.
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
  cat <<'EOF'
Usage:
  bash core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh [--prepare-only]

Default behavior:
1) Prepare env + dependencies
2) Start websocket bridge
3) Start http webhook bridge
4) Start cloudflared tunnel (quick or named based on SOLAR_TUNNEL_MODE)
5) Auto-detect public URL
6) Register + verify Telegram webhook

Option:
  --prepare-only   Run prepare steps only (no long-running services/tunnel)
EOF
}

PREPARE_ONLY="false"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--prepare-only" ]]; then
  PREPARE_ONLY="true"
fi

POETRY_BIN="$(resolve_bin poetry /opt/homebrew/bin/poetry /usr/local/bin/poetry "$HOME/.local/bin/poetry")" || {
  echo "Missing dependency: poetry"
  exit 1
}
CURL_BIN="$(resolve_bin curl /usr/bin/curl /usr/local/bin/curl)" || {
  echo "Missing dependency: curl"
  exit 1
}

bash core/skills/solar-transport-gateway/scripts/onboard_websocket_env.sh
"$POETRY_BIN" -C core/skills/solar-transport-gateway install >/dev/null
bash core/skills/solar-transport-gateway/scripts/validate_websocket_bridge.sh

if [[ "$PREPARE_ONLY" == "true" ]]; then
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

stop_if_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$pid_file"
  fi
}

stop_if_running "$RUN_DIR/ws.pid"
stop_if_running "$RUN_DIR/http.pid"
stop_if_running "$RUN_DIR/cloudflared.pid"

nohup bash core/skills/solar-transport-gateway/scripts/run_websocket_bridge.sh \
  >"$RUN_DIR/ws.log" 2>&1 &
echo $! >"$RUN_DIR/ws.pid"

nohup bash core/skills/solar-transport-gateway/scripts/run_http_webhook_bridge.sh \
  >"$RUN_DIR/http.log" 2>&1 &
echo $! >"$RUN_DIR/http.pid"

host="${SOLAR_HTTP_HOST:-127.0.0.1}"
port="${SOLAR_HTTP_PORT:-8787}"
tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
if [[ "$tunnel_mode" == "named" ]]; then
  tunnel_name="${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}"
  tunnel_config="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
  tunnel_hostname="${SOLAR_CLOUDFLARED_HOSTNAME:-REPLACE_ME}"
  if [[ ! -f "$tunnel_config" ]]; then
    echo "Missing named tunnel config: $tunnel_config"
    echo "Run: bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh"
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
  exit 1
fi

SOLAR_WEBHOOK_PUBLIC_URL="$public_url" \
  bash core/skills/solar-transport-gateway/scripts/set_telegram_webhook.sh >/dev/null
bash core/skills/solar-transport-gateway/scripts/verify_telegram_webhook.sh >/dev/null

echo "Transport gateway setup completed."
echo "Public URL: $public_url"
echo "Processes:"
echo "  ws pid: $(cat "$RUN_DIR/ws.pid")"
echo "  http pid: $(cat "$RUN_DIR/http.pid")"
echo "  tunnel pid: $(cat "$RUN_DIR/cloudflared.pid")"
echo "Logs: $RUN_DIR/{ws.log,http.log,cloudflared.log}"
