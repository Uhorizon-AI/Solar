#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
RUNTIME="$(solar_host_runtime_dir)"
PID_FILE="$SOLAR_HOST_PID_FILE"
LOG_FILE="$RUNTIME/host.log"

host_health_ok() {
  bash "$SCRIPT_DIR/check_host.sh" --liveness >/dev/null 2>&1
}

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if host_health_ok; then
    echo "Solar Host already running (pid $old_pid) — $SOLAR_APP_BASE_URL"
    exit 0
  fi
  # The health check includes identity. Only this runtime's own console may be
  # stopped here: a pid that no longer runs host_server.py is a reused pid, and a
  # host_server.py that answers as another workspace's console is foreign. Both
  # are dropped with the pid file, never killed. The identity is evaluated before
  # the pid file is removed, so the file still counts as a proof for a legacy
  # console that reports no identity.
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if ! solar_host_pid_looks_like_server "$old_pid"; then
      echo "WARN: pid $old_pid in the host pid file is not host_server.py (reused pid) — leaving it running" >&2
    elif [[ "$(solar_host_listener_identity "$old_pid")" == own ]]; then
      echo "WARN: stale Solar Host pid $old_pid (health check failed) — stopping" >&2
      solar_host_stop_pid "$old_pid"
    else
      echo "WARN: pid $old_pid in the host pid file runs host_server.py but is not this runtime's console — leaving it running" >&2
    fi
  fi
  # Never adopt or stop a console of another workspace or runtime; do it before
  # the pid file is dropped so the file still counts as a proof of ownership.
  solar_host_refuse_foreign_listener || exit 3
  rm -f "$PID_FILE"
fi

if host_health_ok; then
  # --liveness already verified the identity, so this listener is our console.
  recovered_pid=""
  recovered_pid="$(solar_host_port_listener_pids | head -n1 || true)"
  if [[ -n "$recovered_pid" ]] && solar_host_pid_looks_like_server "$recovered_pid"; then
    echo "$recovered_pid" >"$PID_FILE"
    echo "Solar Host already running (pid $recovered_pid, recovered pid file) — $SOLAR_APP_BASE_URL"
    exit 0
  fi
fi

# Something still holds the port. If it is this runtime's own hung console (this
# install's host_server.py, no /health answer), stop it so the new process can
# bind; a foreign console is reported once and never stopped, and the run exits 3
# because retrying here cannot converge.
if solar_host_port_listener_pids | grep -q .; then
  set +e
  solar_host_stop_orphan_listeners
  orphan_ec=$?
  set -e
  if [[ "$orphan_ec" -eq 2 ]]; then
    exit 3
  fi
  if [[ "$orphan_ec" -eq 4 ]]; then
    echo "ERROR: the console port :${SOLAR_APP_PORT} is held by an own listener that is not host_server.py; it was not stopped." >&2
    exit 4
  fi
  # Stopping the process does not release the port at the same instant: wait
  # until the listener is really gone before binding, or the bind would fail.
  for _i in 1 2 3 4 5 6 7 8 9 10; do
    solar_host_port_listener_pids | grep -q . || break
    sleep 0.2
  done
  if solar_host_port_listener_pids | grep -q .; then
    solar_host_report_foreign_listener
    exit 3
  fi
fi

export SOLAR_CLI="$SOLAR_WORKSPACE/core/skills/solar-client/scripts/solar"
if [[ ! -f "$SOLAR_CLI" ]] && [[ -f "$(solar_core_dir)/skills/solar-client/scripts/solar" ]]; then
  export SOLAR_CLI="$(solar_core_dir)/skills/solar-client/scripts/solar"
fi

: >>"$LOG_FILE"
new_pid="$(python3 - "$SCRIPT_DIR/host_server.py" "$LOG_FILE" <<'PYTHON'
import subprocess,sys
with open(sys.argv[2], 'ab', buffering=0) as log:
    process = subprocess.Popen([sys.executable, '-u', sys.argv[1]], stdin=subprocess.DEVNULL,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
print(process.pid)
PYTHON
)"
echo "$new_pid" >"$PID_FILE"

ready=false
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 0.2
  if ! kill -0 "$new_pid" 2>/dev/null; then
    break
  fi
  if host_health_ok; then
    ready=true
    break
  fi
done

if [[ "$ready" != true ]]; then
  rm -f "$PID_FILE"
  echo "ERROR: Solar Host failed to start (pid $new_pid)" >&2
  if [[ -f "$LOG_FILE" ]]; then
    echo "--- last lines of $LOG_FILE ---" >&2
    tail -n 20 "$LOG_FILE" >&2 || true
  fi
  if kill -0 "$new_pid" 2>/dev/null; then
    kill "$new_pid" 2>/dev/null || true
  fi
  exit 1
fi

echo "OK: Solar Host started at $SOLAR_APP_BASE_URL (pid $new_pid, log $LOG_FILE)"
