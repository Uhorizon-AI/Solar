#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/interface_lib.sh"

if ! is_interface_pid_alive; then
  rm -f "$SOLAR_INTERFACE_PID_FILE"
  listener_pid="$(get_interface_listener_pid || true)"
  if [[ -n "$listener_pid" ]] && is_interface_server_pid "$listener_pid"; then
    kill "$listener_pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$listener_pid" 2>/dev/null; then
        echo "Solar Interface stopped (listener pid=$listener_pid)."
        exit 0
      fi
      sleep 0.25
    done
    kill -9 "$listener_pid" 2>/dev/null || true
    echo "Solar Interface killed (listener pid=$listener_pid)."
    exit 0
  fi
  echo "Solar Interface is not running."
  exit 0
fi

pid="$(cat "$SOLAR_INTERFACE_PID_FILE")"
kill "$pid" 2>/dev/null || true

for _ in $(seq 1 20); do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$SOLAR_INTERFACE_PID_FILE"
    echo "Solar Interface stopped."
    exit 0
  fi
  sleep 0.25
done

kill -9 "$pid" 2>/dev/null || true
rm -f "$SOLAR_INTERFACE_PID_FILE"
echo "Solar Interface killed."
