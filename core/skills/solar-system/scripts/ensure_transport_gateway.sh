#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

check_cmd="bash core/skills/solar-transport-gateway/scripts/check_transport_gateway.sh"
setup_cmd="bash core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh"
run_dir="${SOLAR_GATEWAY_RUN_DIR:-/tmp/solar-transport-gateway}"

stop_existing_tunnel() {
  local pid_file="$run_dir/cloudflared.pid"
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

set +e
check_out="$($check_cmd 2>&1)"
check_code=$?
set -e

if [[ -n "$check_out" ]]; then
  echo "$check_out"
fi

case "$check_code" in
  0)
    echo "✅ Transport gateway healthy. No action needed."
    exit 0
    ;;
  1)
    echo "⚠️  Transport gateway is down. Running setup recovery..."
    $setup_cmd
    ;;
  2)
    # Partial = local bridge healthy, public tunnel degraded.
    # Use tunnel-only recovery to avoid full setup side effects (for example .env rewrites).
    echo "⚠️  Transport gateway partial state detected. Restarting tunnel only..."
    mkdir -p "$run_dir"
    stop_existing_tunnel
    nohup bash core/skills/solar-transport-gateway/scripts/start_cloudflared_tunnel.sh \
      >"$run_dir/cloudflared.log" 2>&1 &
    echo $! >"$run_dir/cloudflared.pid"
    sleep 1
    if ! kill -0 "$(cat "$run_dir/cloudflared.pid")" 2>/dev/null; then
      echo "❌ Tunnel recovery failed to start cloudflared process." >&2
      exit 1
    fi
    echo "✅ Tunnel recovery started (pid $(cat "$run_dir/cloudflared.pid"))."
    ;;
  *)
    echo "❌ Unexpected transport gateway check code: $check_code" >&2
    exit "$check_code"
    ;;
esac
