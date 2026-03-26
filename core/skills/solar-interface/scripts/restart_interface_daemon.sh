#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/stop_interface_daemon.sh" >/dev/null || true
exec bash "$SCRIPT_DIR/start_interface_daemon.sh"
