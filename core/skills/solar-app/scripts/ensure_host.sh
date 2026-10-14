#!/usr/bin/env bash
# Ensure Solar Host UI (:9000). Workspace API is in-process (no separate :7741 daemon).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env

if bash "$SCRIPT_DIR/check_host.sh" --liveness; then
  exit 0
fi

# A console of another workspace or runtime is never adopted and never stopped.
# Report it once and stop: retrying here cannot converge.
if solar_host_port_listener_pids | grep -q .; then
  if ! solar_host_listener_identity_matches; then
    solar_host_report_foreign_listener
    exit 3
  fi
fi

exec bash "$SCRIPT_DIR/start_host.sh"
