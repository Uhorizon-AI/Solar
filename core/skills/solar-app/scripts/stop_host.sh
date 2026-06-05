#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
PID_FILE="$SOLAR_HOST_PID_FILE"
stopped=0
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    solar_host_stop_pid "$pid"
    stopped=1
  fi
  rm -f "$PID_FILE"
else
  if solar_host_stop_orphan_listeners; then
    stopped=1
  fi
fi
if [[ "$stopped" -eq 1 ]]; then
  echo "OK: Solar Host stopped"
else
  echo "Solar Host not running (no pid file, no listener on :${SOLAR_APP_PORT})"
fi
