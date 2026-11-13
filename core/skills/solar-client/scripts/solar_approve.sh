#!/usr/bin/env bash
# solar_approve.sh — operator approval channel (`solar approve`), run from the workspace.
# Resolves the workspace from the current directory like `solar status`; an exported
# SOLAR_WORKSPACE that disagrees with it fails instead of being guessed. The approval
# screen names the resolved workspace before the operator types yes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$SCRIPT_DIR/../../solar-paths/scripts/resolve_solar_paths.sh"
solar_resolve_paths --quiet

MCP_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-mcp/scripts" && pwd)"
exec "${SOLAR_MCP_PYTHON:-python3}" "$MCP_SCRIPTS/operator_approve.py" "$@"
