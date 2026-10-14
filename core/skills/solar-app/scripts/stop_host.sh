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

# Stop the pid-file process only when it is this runtime's own console AND it is
# the process that actually listens on the port. A reused pid, another workspace's
# console, or a live own pid that is not the listener is dropped, never killed:
# killing the pid file while another process holds :9000 would leave the port
# occupied by the process nobody stopped. The pid is the value already read
# above, so the file is not read a second time.
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    live_pids="$(solar_host_port_listener_pids || true)"
    endpoint_state="$(solar_host_endpoint_state_for "$pid" "$(solar_host_port_endpoints)")"
    if ! kill -0 "$pid" 2>/dev/null; then
      # The pid is gone: the file is stale, not a reused pid. Dropping it is the
      # whole job here; there is nothing to leave running.
      echo "WARN: stale pid $pid in the host pid file (process is gone) — dropping the pid file" >&2
    elif [[ "$endpoint_state" == other ]]; then
      # The pid serves the same port on a different address (or family), not the
      # socket SOLAR_APP_BASE_URL reaches: it is not the console this runtime
      # talks to, and killing it would stop a console on another socket. Leave it
      # running; the sweep below only covers listeners of the probed endpoint.
      echo "WARN: pid $pid in the host pid file listens on :${SOLAR_APP_PORT} at another address — leaving it running" >&2
    elif ! solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: pid $pid in the host pid file is not a live host_server.py (reused pid) — leaving it running" >&2
    elif [[ -n "$live_pids" ]] && ! grep -qx "$pid" <<<"$live_pids"; then
      # A live own host_server.py that is not one of the port's listeners: killing
      # it would not free :$SOLAR_APP_PORT. Drop the file; the port sweep below
      # stops the process that really listens. The whole listener list is checked,
      # not just the first: with several listeners, a valid pid beyond the first
      # must not be discarded as "not the listener".
      echo "WARN: pid $pid in the host pid file is not a listener on :${SOLAR_APP_PORT} — leaving it running" >&2
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
