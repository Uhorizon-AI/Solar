#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"
solar_resolve_paths --quiet
bash "$(solar_core_dir)/scripts/sync-clients.sh" "$@"
solar_client_bump_manifest_from_install "$SOLAR_WORKSPACE" "$SOLAR_ROOT"
solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
