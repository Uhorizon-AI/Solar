#!/usr/bin/env bash
# Stop this runtime's console. Only a live host_server.py is ever signalled, and
# never one that serves another workspace or runtime (host_identity.py).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
PID_FILE="$SOLAR_HOST_PID_FILE"
stopped=0
solar_host_assess
case "$HOST_STATE" in
  mismatch)
    solar_host_explain_refusal
    exit 3
    ;;
esac
if [[ -f "$PID_FILE" ]]; then
  pid="$(solar_host_pidfile_pid "$HOST_STATE" || true)"
  if [[ -n "$pid" ]]; then
    solar_host_stop_pid "$pid" && stopped=1
  else
    echo "WARN: stale pid file (no live host_server.py behind it); no process was signalled" >&2
  fi
  rm -f "$PID_FILE"
fi
if [[ "$stopped" -ne 1 ]] && solar_host_stop_orphan_listeners; then
  stopped=1
fi
if [[ "$stopped" -eq 1 ]]; then
  echo "OK: Solar Host stopped"
else
  echo "Solar Host not running (no stoppable console for this runtime on :${SOLAR_APP_PORT})"
fi
