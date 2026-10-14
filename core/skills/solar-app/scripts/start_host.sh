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

# One decision, from the identity policy (host_identity.py), before anything is
# started or stopped. A process is only ever stopped when it is a host_server.py
# AND provably this runtime's console (see host_lib.sh). No retry loop.
solar_host_assess
pidfile_pid="$(solar_host_pidfile_pid "$HOST_STATE" || true)"

case "$HOST_STATE" in
  match)
    if [[ -n "$pidfile_pid" ]]; then
      echo "Solar Host already running (pid $pidfile_pid) — $SOLAR_APP_BASE_URL"
      exit 0
    fi
    # The console is ours (identity) but the pid file is missing or stale: repair it
    # with the pid the console reported itself, after checking it is a host_server.py.
    if [[ -n "$HOST_OBSERVED_PID" ]] && solar_host_pid_looks_like_server "$HOST_OBSERVED_PID"; then
      echo "$HOST_OBSERVED_PID" >"$PID_FILE"
      echo "Solar Host already running (pid $HOST_OBSERVED_PID, pid file repaired) — $SOLAR_APP_BASE_URL"
    else
      rm -f "$PID_FILE"
      echo "Solar Host already running (pid not reported by this console) — $SOLAR_APP_BASE_URL"
    fi
    exit 0
    ;;
  stale_workspace)
    # Our own console, still serving the workspace that was active before a switch.
    echo "WARN: Solar Host pid $HOST_OBSERVED_PID serves the previous workspace (${HOST_OBSERVED_WORKSPACE}); restarting it on ${SOLAR_WORKSPACE}" >&2
    solar_host_stop_pid "$HOST_OBSERVED_PID" || { solar_host_explain_refusal; exit 3; }
    rm -f "$PID_FILE"
    sleep 0.3
    ;;
  mismatch|invalid)
    solar_host_explain_refusal
    exit 3
    ;;
  legacy|partial)
    # Older console without (full) identity: it is replaced only if shown to be
    # ours, by this runtime's pid file or by this install's script path.
    adopted=0
    while IFS= read -r p; do
      [[ -z "$p" ]] && continue
      solar_host_pid_looks_like_server "$p" || continue
      if [[ "$p" == "$pidfile_pid" ]] || solar_host_pid_is_this_install "$p"; then
        echo "WARN: adopting Solar Host pid $p that reports no full identity; replacing it with a console that does" >&2
        solar_host_stop_pid "$p" && adopted=1
      fi
    done < <(solar_host_port_listener_pids)
    if [[ "$adopted" -ne 1 ]]; then
      solar_host_explain_refusal
      echo "  Ownership of that console could not be shown (no pid file for this runtime, and not this install's host_server.py)." >&2
      exit 3
    fi
    rm -f "$PID_FILE"
    sleep 0.3
    ;;
  *)
    # Nothing usable answers. A recorded pid that is still a host_server.py is a hung
    # or half-started console of this runtime; a stale file is just removed.
    if [[ -n "$pidfile_pid" ]]; then
      echo "WARN: Solar Host pid $pidfile_pid does not answer — stopping" >&2
      solar_host_stop_pid "$pidfile_pid" || true
    fi
    rm -f "$PID_FILE"
    if [[ -n "$(solar_host_port_listener_pids)" ]]; then
      echo "WARN: port :$SOLAR_APP_PORT is held by a process that does not answer — stopping it only if it is this install's console" >&2
      solar_host_stop_orphan_listeners || true
      sleep 0.3
      if [[ -n "$(solar_host_port_listener_pids)" ]]; then
        HOST_REASON="the port is held by a process that cannot be shown to be this console"
        HOST_OBSERVED_WORKSPACE="" HOST_OBSERVED_RUNTIME=""
        solar_host_explain_refusal
        exit 3
      fi
    fi
    ;;
esac

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
