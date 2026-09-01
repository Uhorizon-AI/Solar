#!/usr/bin/env bash
# client_self_update.sh — align global Solar Client install (Fase 3D).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

exec bash "$SCRIPT_DIR/client_update.sh" "$@"
