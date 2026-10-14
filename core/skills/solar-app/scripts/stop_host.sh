#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
PID_FILE="$SOLAR_HOST_PID_FILE"
stopped=0
foreign=0
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    # The same proof start_host.sh uses: only a live host_server.py is ours.
    # A pid reused by another program is dropped, never killed.
    if solar_host_pid_file_is_own_server "$pid"; then
      solar_host_stop_pid "$pid"
      stopped=1
    else
      echo "WARN: pid $pid in the host pid file is not a live host_server.py (reused pid) — leaving it running" >&2
    fi
  fi
  rm -f "$PID_FILE"
else
  set +e
  solar_host_stop_orphan_listeners
  listeners_ec=$?
  set -e
  case "$listeners_ec" in
    0) stopped=1 ;;
    2) foreign=1 ;;
    *) : ;;
  esac
fi
if [[ "$foreign" -eq 1 ]]; then
  # The listener is another workspace's or runtime's console: it was reported
  # and left running, so this is not a clean stop.
  exit 3
fi
if [[ "$stopped" -eq 1 ]]; then
  echo "OK: Solar Host stopped"
else
  echo "Solar Host not running (no pid file, no listener on :${SOLAR_APP_PORT})"
fi
