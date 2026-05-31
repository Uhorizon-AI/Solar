#!/usr/bin/env bash
# Ensure Solar Host UI (:9000) and its API backend (solar-interface daemon on :7741).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env

_INTERFACE_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-interface/scripts" && pwd)"

# Host depends on the interface daemon (approvals, chat, threads). One feature token: `host`.
if ! bash "$_INTERFACE_SCRIPTS/ensure_interface.sh"; then
  echo "ERROR: solar-interface backend required for Host" >&2
  exit 1
fi

if bash "$SCRIPT_DIR/check_host.sh" --quiet; then
  exit 0
fi

exec bash "$SCRIPT_DIR/start_host.sh"
