#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
PID_FILE="$SOLAR_HOST_PID_FILE"
if [[ ! -f "$PID_FILE" ]]; then
  echo "Solar Host not running (no pid file)"
  exit 0
fi
pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  sleep 0.2
fi
rm -f "$PID_FILE"
echo "OK: Solar Host stopped"
