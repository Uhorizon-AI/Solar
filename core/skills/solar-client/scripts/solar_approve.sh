#!/usr/bin/env bash
# solar_approve.sh — operator approval channel (`solar approve`).
# Workspace: SOLAR_WORKSPACE when it is exported, else the one that contains the current directory
# (like `solar status`). An exported SOLAR_WORKSPACE is honoured from any directory, but it fails
# when the current directory belongs to a different workspace: it is never guessed. The approval
# screen names the resolved workspace before the operator types yes. `--help` needs no workspace.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVER="$SCRIPT_DIR/../../solar-paths/scripts/resolve_solar_paths.sh"
MCP_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-mcp/scripts" && pwd)"
APPROVE=("${SOLAR_MCP_PYTHON:-python3}" "$MCP_SCRIPTS/operator_approve.py")

case "${1:-}" in
  ""|-h|--help) exec "${APPROVE[@]}" "$@" ;;
esac

# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$RESOLVER"

if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
  # Does the current directory belong to a workspace? Ask the resolver without the variable.
  found="$(env -u SOLAR_WORKSPACE bash -c 'source "$1" && solar_resolve_paths --export' _ "$RESOLVER" 2>/dev/null \
    | sed -n 's/^SOLAR_WORKSPACE=//p' || true)"
  if [[ -n "$found" ]]; then
    solar_resolve_paths --quiet                                   # same workspace passes; another one conflicts
  else
    solar_resolve_paths --workspace "$SOLAR_WORKSPACE" --quiet    # outside any workspace: the variable decides
  fi
else
  solar_resolve_paths --quiet
fi

exec "${APPROVE[@]}" "$@"
