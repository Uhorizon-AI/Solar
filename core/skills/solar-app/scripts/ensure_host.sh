#!/usr/bin/env bash
# Ensure Solar Host UI (:9000). Workspace API is in-process (no separate :7741 daemon).
# A console is reused only if its identity matches (check_host.sh --liveness);
# otherwise start_host.sh decides once: replace a console proven to be ours, or
# refuse with a diagnostic. There is no retry loop.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env

if bash "$SCRIPT_DIR/check_host.sh" --liveness; then
  exit 0
fi

exec bash "$SCRIPT_DIR/start_host.sh"
