#!/usr/bin/env bash
# Ensure transport gateway is healthy; recover with drift-aware restart.
#
# Used by solar-system orchestrator each tick.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

check_cmd="bash $(transport_gateway_script check_transport_gateway.sh)"
setup_cmd="bash $(transport_gateway_script setup_transport_gateway.sh)"
start_tunnel_cmd="bash $(transport_gateway_script start_cloudflared_tunnel.sh)"
stop_cmd="bash $(transport_gateway_script stop_transport_gateway.sh)"
run_dir="$(gateway_run_dir)"

# 1. Gateway lock (distinct from orchestrator lock).
if ! gateway_acquire_lock; then
  exit 0
fi
gateway_install_lock_trap

# 2. Backoff / hard-stop for same failed fingerprint.
if gateway_backoff_active; then
  if gateway_fail_exhausted; then
    attempts="$(grep -E '^attempts=' "$(gateway_fail_path)" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
    echo "❌ Gateway fail cap reached (attempts=${attempts:-?}/${GATEWAY_FAIL_ATTEMPTS_CAP}, same fingerprint)." >&2
    echo "   Fix .env (or remove sun/runtime/gateway/env.fail) then rerun setup manually." >&2
    exit 0
  fi
  next_at="$(grep -E '^next_retry_at=' "$(gateway_fail_path)" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  echo "⏸️  Gateway backoff active until epoch ${next_at:-?} (same failed fingerprint). Skipping."
  exit 0
fi

run_setup_restart() {
  # Parent holds lock; child must not re-acquire / release.
  SOLAR_GATEWAY_LOCK_HELD=1 $setup_cmd --restart
}

# 3. Drift first (prevails over partial).
if gateway_has_drift; then
  echo "⚠️  Env drift detected (stamp mismatch or missing stamp with live bridges)."
  if ! gateway_preflight; then
    echo "❌ Preflight failed on drift — leaving healthy/current runtime untouched." >&2
    gateway_write_env_fail "preflight_failed_drift"
    exit 1
  fi
  echo "Running setup --restart after successful preflight..."
  run_setup_restart
  exit $?
fi

# 4. No drift → check health.
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
    if ! gateway_preflight; then
      echo "❌ Preflight failed — not starting." >&2
      gateway_write_env_fail "preflight_failed_down"
      exit 1
    fi
    run_setup_restart
    ;;
  2)
    echo "⚠️  Transport gateway partial state (no drift). Restarting tunnel only..."
    mkdir -p "$run_dir"
    $stop_cmd --tunnel-only || true
    nohup $start_tunnel_cmd >"$run_dir/cloudflared.log" 2>&1 &
    echo $! >"$run_dir/cloudflared.pid"
    sleep 1
    if ! kill -0 "$(cat "$run_dir/cloudflared.pid")" 2>/dev/null; then
      echo "❌ Tunnel recovery failed to start cloudflared process." >&2
      gateway_write_env_fail "tunnel_recovery_failed"
      exit 1
    fi
    echo "✅ Tunnel recovery started (pid $(cat "$run_dir/cloudflared.pid"))."
    ;;
  *)
    echo "❌ Unexpected transport gateway check code: $check_code" >&2
    exit "$check_code"
    ;;
esac
