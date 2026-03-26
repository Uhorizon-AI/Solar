#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/interface_lib.sh"

ensure_interface_dirs

MIGRATION_SOURCE="$SCRIPT_DIR/../references/001_initial.sql"
cp "$MIGRATION_SOURCE" "$SOLAR_INTERFACE_MIGRATIONS_DIR/001_initial.sql"

python3 "$SCRIPT_DIR/interface_server.py" --setup-only

echo "Solar Interface runtime ready at: $SOLAR_INTERFACE_RUNTIME_DIR_ABS"
