#!/usr/bin/env bash
# Ensure Solar Host UI (:9000). Workspace API is in-process (no separate :7741 daemon).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env

if bash "$SCRIPT_DIR/check_host.sh" --quiet; then
  exit 0
fi

exec bash "$SCRIPT_DIR/start_host.sh"
