#!/usr/bin/env bash
# Smoke: change SOLAR_ROUTER_PROVIDER_PRIORITY → ensure → new bridge loads updated value.
#
# Usage (from workspace or with SOLAR_WORKSPACE set):
#   bash core/tests/skills/solar-gateway/smoke_priority_ensure.sh
#
# Optional:
#   SMOKE_KEEP=1  — do not restore original priority after success
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LIB="$CORE_ROOT/skills/solar-gateway/scripts/transport_gateway_lib.sh"
ENSURE="$CORE_ROOT/skills/solar-gateway/scripts/ensure_transport_gateway.sh"
STOP="$CORE_ROOT/skills/solar-gateway/scripts/stop_transport_gateway.sh"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# shellcheck source=/dev/null
source "$LIB"
transport_gateway_bind_workspace

ENV_FILE="$SOLAR_WORKSPACE/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "FAIL: missing $ENV_FILE" >&2
  exit 1
fi

original_present=0
if grep -Eq '^SOLAR_ROUTER_PROVIDER_PRIORITY=' "$ENV_FILE"; then
  original_present=1
fi
original="$(grep -E '^SOLAR_ROUTER_PROVIDER_PRIORITY=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"
if [[ -z "$original" ]]; then
  original="${SOLAR_ROUTER_PROVIDER_PRIORITY:-codex,claude,agent}"
fi

# Distinct smoke value (must be supported providers).
smoke_priority="codex,claude,agy"
if [[ "$original" == "$smoke_priority" ]]; then
  smoke_priority="codex,agy,claude"
fi

process_env_has_priority() {
  local pid="$1"
  local want="$2"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # macOS: ps eww; Linux: /proc/PID/environ
  local envdump=""
  if [[ -r "/proc/$pid/environ" ]]; then
    envdump="$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null || true)"
  else
    envdump="$(ps eww -p "$pid" 2>/dev/null || ps -E -p "$pid" 2>/dev/null || true)"
  fi
  printf '%s' "$envdump" | grep -Fq "SOLAR_ROUTER_PROVIDER_PRIORITY=${want}"
}

restore_env_file() {
  local tmp
  tmp="$(mktemp)"
  if [[ "$original_present" == "1" ]]; then
    awk -v v="SOLAR_ROUTER_PROVIDER_PRIORITY=${original}" '
      /^SOLAR_ROUTER_PROVIDER_PRIORITY=/ { print v; next }
      { print }
    ' "$ENV_FILE" >"$tmp"
  else
    awk '
      !/^SOLAR_ROUTER_PROVIDER_PRIORITY=/
    ' "$ENV_FILE" >"$tmp"
  fi
  mv "$tmp" "$ENV_FILE"
}

smoke_cleanup() {
  local smoke_status=$?
  trap - EXIT
  if [[ "${SMOKE_KEEP:-}" == "1" ]]; then
    exit "$smoke_status"
  fi

  set +e
  restore_env_file
  local env_restore_code=$?
  if [[ "$env_restore_code" -ne 0 ]]; then
    echo "FAIL: could not restore SOLAR_ROUTER_PROVIDER_PRIORITY in $ENV_FILE" >&2
    exit 1
  fi

  echo "== smoke: restoring original priority via ensure"
  local restore_out restore_code
  restore_out="$(bash "$ENSURE" 2>&1)"
  restore_code=$?
  if [[ "$restore_code" -ne 0 ]]; then
    echo "$restore_out" >&2
    echo "FAIL: ensure could not restore the gateway runtime" >&2
    exit 1
  fi

  # Re-read the restored env and prove runtime + stamp are aligned and healthy.
  unset SOLAR_ROUTER_PROVIDER_PRIORITY
  _TGW_BOUND=
  transport_gateway_bind_workspace
  local restored_priority current_fp stamped_fp run_dir ws_pid http_pid
  restored_priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-codex,claude,agy,agent}}"
  current_fp="$(gateway_compute_fingerprint)"
  stamped_fp="$(gateway_stamp_get fingerprint 2>/dev/null || true)"
  if [[ -z "$stamped_fp" || "$current_fp" != "$stamped_fp" ]]; then
    echo "FAIL: restored env fingerprint does not match env.stamp" >&2
    exit 1
  fi
  if ! bash "$(transport_gateway_script check_transport_gateway.sh)" >/dev/null 2>&1; then
    echo "FAIL: gateway is not healthy after smoke restoration" >&2
    exit 1
  fi

  run_dir="$(gateway_run_dir)"
  ws_pid="$(cat "$run_dir/ws.pid" 2>/dev/null || true)"
  http_pid="$(cat "$run_dir/http.pid" 2>/dev/null || true)"
  if ! process_env_has_priority "$ws_pid" "$restored_priority" \
    && ! process_env_has_priority "$http_pid" "$restored_priority"; then
    echo "FAIL: restored gateway processes do not contain priority=$restored_priority" >&2
    exit 1
  fi
  echo "PASS: original priority restored; gateway healthy and stamp aligned"
  exit "$smoke_status"
}
trap smoke_cleanup EXIT

echo "== smoke: original priority=$original"
echo "== smoke: writing priority=$smoke_priority"

tmp="$(mktemp)"
if grep -Eq '^SOLAR_ROUTER_PROVIDER_PRIORITY=' "$ENV_FILE"; then
  awk -v v="SOLAR_ROUTER_PROVIDER_PRIORITY=${smoke_priority}" '
    /^SOLAR_ROUTER_PROVIDER_PRIORITY=/ { print v; next }
    { print }
  ' "$ENV_FILE" >"$tmp"
  mv "$tmp" "$ENV_FILE"
else
  echo "SOLAR_ROUTER_PROVIDER_PRIORITY=${smoke_priority}" >>"$ENV_FILE"
fi

# Re-bind so fingerprint/drift see the new value.
_TGW_BOUND=
transport_gateway_bind_workspace

if ! gateway_has_drift; then
  # Force stamp mismatch for smoke when stamp was absent/matching oddly.
  rm -f "$(gateway_stamp_path)"
  # Live bridges + missing stamp = drift
  if ! gateway_has_drift; then
    echo "WARN: no drift detected (no live bridges?). Continuing with ensure anyway."
  fi
fi

echo "== smoke: running ensure_transport_gateway.sh"
set +e
ensure_out="$(bash "$ENSURE" 2>&1)"
ensure_code=$?
set -e
echo "$ensure_out"
echo "== smoke: ensure exit=$ensure_code"
if [[ "$ensure_code" -ne 0 ]]; then
  echo "FAIL: ensure failed during priority smoke" >&2
  exit 1
fi

run_dir="$(gateway_run_dir)"
ws_pid=""
http_pid=""
if [[ -f "$run_dir/ws.pid" ]]; then
  ws_pid="$(cat "$run_dir/ws.pid" 2>/dev/null || true)"
fi
if [[ -f "$run_dir/http.pid" ]]; then
  http_pid="$(cat "$run_dir/http.pid" 2>/dev/null || true)"
fi

echo "== smoke: ws.pid=${ws_pid:-missing} http.pid=${http_pid:-missing}"

ok=0
if process_env_has_priority "$ws_pid" "$smoke_priority"; then
  echo "PASS: ws process env has SOLAR_ROUTER_PROVIDER_PRIORITY=$smoke_priority"
  ok=1
elif process_env_has_priority "$http_pid" "$smoke_priority"; then
  echo "PASS: http process env has SOLAR_ROUTER_PROVIDER_PRIORITY=$smoke_priority"
  ok=1
else
  # Fallback evidence: stop --dry-run reports priority for owned bridges
  dry="$(bash "$STOP" --dry-run 2>&1 || true)"
  echo "$dry"
  if printf '%s' "$dry" | grep -q "priority=${smoke_priority}"; then
    echo "PASS: stop --dry-run reports priority=$smoke_priority on owned bridges"
    ok=1
  fi
fi

if [[ "$ok" -ne 1 ]]; then
  echo "FAIL: could not verify updated priority on new gateway process" >&2
  exit 1
fi

stamped="$(grep -E '^fingerprint=' "$(gateway_stamp_path)" 2>/dev/null | cut -d= -f2- || true)"
echo "== smoke: stamp fingerprint=${stamped:0:16}..."
echo "PASS: priority smoke complete"
exit 0
