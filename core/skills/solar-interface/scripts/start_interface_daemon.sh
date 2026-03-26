#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/interface_lib.sh"

ensure_interface_dirs
bash "$SCRIPT_DIR/setup_interface.sh" >/dev/null

if is_interface_pid_alive; then
  echo "Solar Interface already running (pid=$(cat "$SOLAR_INTERFACE_PID_FILE"))."
  exit 0
fi

listener_pid="$(get_interface_listener_pid || true)"
if [[ -n "$listener_pid" ]]; then
  if is_interface_server_pid "$listener_pid"; then
    echo "$listener_pid" >"$SOLAR_INTERFACE_PID_FILE"
    if bash "$SCRIPT_DIR/check_interface.sh" --quiet; then
      echo "Solar Interface already listening on :$SOLAR_INTERFACE_PORT (pid=$listener_pid)."
      exit 0
    fi
    echo "Solar Interface daemon is already listening on :$SOLAR_INTERFACE_PORT but is not ready (pid=$listener_pid)." >&2
    echo "Run: bash core/skills/solar-interface/scripts/restart_interface_daemon.sh" >&2
    exit 1
  fi
  echo "Solar Interface cannot start: port $SOLAR_INTERFACE_PORT is already in use by pid=$listener_pid." >&2
  echo "Stop that process or change SOLAR_INTERFACE_PORT in .env." >&2
  exit 1
fi

nohup python3 "$SCRIPT_DIR/interface_server.py" >"$SOLAR_INTERFACE_STDOUT_LOG" 2>"$SOLAR_INTERFACE_STDERR_LOG" &
pid=$!
echo "$pid" >"$SOLAR_INTERFACE_PID_FILE"

for _ in $(seq 1 20); do
  if bash "$SCRIPT_DIR/check_interface.sh" --quiet; then
    echo "Solar Interface started (pid=$pid)."
    exit 0
  fi
  sleep 0.25
done

listener_pid="$(get_interface_listener_pid || true)"
if [[ -n "$listener_pid" ]] && is_interface_server_pid "$listener_pid"; then
  echo "$listener_pid" >"$SOLAR_INTERFACE_PID_FILE"
  echo "Solar Interface is listening on :$SOLAR_INTERFACE_PORT but failed readiness checks (pid=$listener_pid)." >&2
else
  rm -f "$SOLAR_INTERFACE_PID_FILE"
fi

echo "Solar Interface failed to start." >&2
exit 1
