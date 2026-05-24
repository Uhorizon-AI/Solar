#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_home.sh
source "$SCRIPT_DIR/resolve_solar_home.sh"
solar_resolve_home --quiet
bash "$SOLAR_CORE_ROOT/scripts/sync-clients.sh" "$@"
