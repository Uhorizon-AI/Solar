#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/interface_lib.sh"

echo "Solar Interface"
echo "  base_url:  $SOLAR_INTERFACE_BASE_URL"
echo "  runtime:   $SOLAR_INTERFACE_RUNTIME_DIR_ABS"
echo "  db:        $SOLAR_INTERFACE_DB_PATH"
echo "  pid_file:  $SOLAR_INTERFACE_PID_FILE"

if bash "$SCRIPT_DIR/check_interface.sh" --quiet; then
  echo "  health:    healthy"
else
  echo "  health:    down"
fi

if is_interface_pid_alive; then
  echo "  pid:       $(cat "$SOLAR_INTERFACE_PID_FILE")"
elif listener_pid="$(get_interface_listener_pid || true)" && [[ -n "$listener_pid" ]]; then
  echo "  pid:       <none>"
  echo "  listener:  $listener_pid"
else
  echo "  pid:       <none>"
fi
