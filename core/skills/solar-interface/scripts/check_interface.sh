#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/interface_lib.sh"

QUIET=false
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=true
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "DOWN: missing_curl: curl is required." >&2
  exit 1
fi

if $QUIET; then
  curl_cmd=(curl --silent --fail --max-time 2 "$SOLAR_INTERFACE_BASE_URL/ready")
else
  curl_cmd=(curl --silent --show-error --fail --max-time 2 "$SOLAR_INTERFACE_BASE_URL/ready")
fi

if "${curl_cmd[@]}" >/dev/null 2>&1; then
  $QUIET || echo "HEALTHY: solar-interface ready at $SOLAR_INTERFACE_BASE_URL"
  exit 0
fi

if [[ ! -d "$SOLAR_INTERFACE_RUNTIME_DIR_ABS" ]] || [[ ! -f "$SOLAR_INTERFACE_DB_PATH" ]]; then
  $QUIET || echo "DOWN: not_setup: runtime or database missing under $SOLAR_INTERFACE_RUNTIME_DIR" >&2
  exit 1
fi

if [[ -f "$SOLAR_INTERFACE_PID_FILE" ]] && ! is_interface_pid_alive; then
  $QUIET || echo "DOWN: stale_pid: pid file exists but process is not alive" >&2
  exit 1
fi

listener_pid="$(get_interface_listener_pid || true)"
if [[ -n "$listener_pid" ]]; then
  if ! is_interface_server_pid "$listener_pid"; then
    $QUIET || echo "DOWN: port_conflict: port $SOLAR_INTERFACE_PORT is occupied by pid=$listener_pid" >&2
    exit 1
  fi

  health_url="$SOLAR_INTERFACE_BASE_URL/health"
  if ! curl --silent --fail --max-time 2 "$health_url" >/dev/null 2>&1; then
    $QUIET || echo "DOWN: unreachable: daemon pid=$listener_pid is listening on port $SOLAR_INTERFACE_PORT but health endpoint failed" >&2
    exit 1
  fi

  $QUIET || echo "DOWN: not_ready: daemon is alive on port $SOLAR_INTERFACE_PORT but readiness checks failed" >&2
  exit 1
fi

if [[ -f "$SOLAR_INTERFACE_STDERR_LOG" ]]; then
  last_error="$(tail -n 20 "$SOLAR_INTERFACE_STDERR_LOG" 2>/dev/null | tr '\n' ' ' || true)"
  if [[ -n "$last_error" ]]; then
    if echo "$last_error" | grep -qi "PermissionError"; then
      $QUIET || echo "DOWN: start_failed: permission error while binding local server" >&2
      exit 1
    fi
    if echo "$last_error" | grep -qi "Address already in use"; then
      $QUIET || echo "DOWN: start_failed: interface port already in use" >&2
      exit 1
    fi
    if echo "$last_error" | grep -qi "Traceback\\|Error\\|Exception"; then
      $QUIET || echo "DOWN: start_failed: daemon exited with recent error logged" >&2
      exit 1
    fi
  fi
fi

$QUIET || echo "DOWN: unreachable: solar-interface not reachable at $SOLAR_INTERFACE_BASE_URL" >&2
exit 1
