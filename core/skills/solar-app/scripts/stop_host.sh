#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
PID_FILE="$SOLAR_HOST_PID_FILE"
stopped=0
foreign=0
unstoppable=0

# Stop the pid-file process only when it is this runtime's own console; a reused
# pid or another workspace's console is dropped, never killed. The pid is the
# value already read above, so the file is not read a second time.
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    if ! solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: pid $pid in the host pid file is not a live host_server.py (reused pid) — leaving it running" >&2
    elif [[ "$(solar_host_listener_identity "$pid")" == own ]]; then
      solar_host_stop_pid "$pid"
      stopped=1
    else
      echo "WARN: pid $pid in the host pid file runs host_server.py but is not this runtime's console — leaving it running" >&2
    fi
  fi
  rm -f "$PID_FILE"
fi

# Whatever the pid file said (or did not), the port may still be held: an own
# console whose pid file was dropped or reused has to be stopped too, and a
# foreign console must not be reported as a clean stop.
set +e
solar_host_stop_orphan_listeners
listeners_ec=$?
set -e
case "$listeners_ec" in
  0) stopped=1 ;;
  2) foreign=1 ;;
  4) unstoppable=1 ;;
  *) : ;;
esac
if [[ "$foreign" -eq 1 || "$unstoppable" -eq 1 ]]; then
  # A foreign console (3) or an own listener that cannot be stopped (4) was
  # reported and left running: reporting "not running" would be a lie.
  set +e
  solar_host_report_port_blocker "$listeners_ec"
  blocker_ec=$?
  set -e
  exit "$blocker_ec"
fi
if [[ "$stopped" -eq 1 ]]; then
  echo "OK: Solar Host stopped"
else
  echo "Solar Host not running (no pid file, no listener on :${SOLAR_APP_PORT})"
fi
