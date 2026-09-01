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
  curl -fsS --max-time 3 "$SOLAR_APP_BASE_URL/health" >/dev/null 2>&1
}

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if host_health_ok; then
      echo "Solar Host already running (pid $old_pid) — $SOLAR_APP_BASE_URL"
      exit 0
    fi
    echo "WARN: stale Solar Host pid $old_pid (health check failed) — stopping" >&2
    solar_host_stop_pid "$old_pid"
  fi
  rm -f "$PID_FILE"
fi

if host_health_ok; then
  orphan_pid=""
  orphan_pid="$(solar_host_port_listener_pids | head -n1 || true)"
  if [[ -n "$orphan_pid" ]] && solar_host_pid_looks_like_server "$orphan_pid"; then
    echo "$orphan_pid" >"$PID_FILE"
    echo "Solar Host already running (orphan pid $orphan_pid, recovered pid file) — $SOLAR_APP_BASE_URL"
    exit 0
  fi
fi

if solar_host_port_listener_pids | grep -q .; then
  echo "WARN: port :$SOLAR_APP_PORT in use — stopping orphan host_server listeners" >&2
  solar_host_stop_orphan_listeners || true
  sleep 0.3
fi

export SOLAR_CLI="$SOLAR_WORKSPACE/core/skills/solar-client/scripts/solar"
if [[ ! -f "$SOLAR_CLI" ]] && [[ -f "$(solar_core_dir)/skills/solar-client/scripts/solar" ]]; then
  export SOLAR_CLI="$(solar_core_dir)/skills/solar-client/scripts/solar"
fi

: >>"$LOG_FILE"
nohup python3 "$SCRIPT_DIR/host_server.py" >>"$LOG_FILE" 2>&1 &
new_pid=$!
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

if [[ "${SOLAR_HOST_TRAY:-}" == "1" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
  python3 "$SCRIPT_DIR/host_platform/macos/launch.py" start-tray 2>/dev/null || true
fi
