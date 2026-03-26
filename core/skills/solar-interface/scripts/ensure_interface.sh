#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if bash "$SCRIPT_DIR/check_interface.sh" --quiet; then
  exit 0
fi

exec bash "$SCRIPT_DIR/start_interface_daemon.sh"
