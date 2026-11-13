#!/usr/bin/env bash
# solar_approve.sh — operator approval channel (`solar approve`).
# Workspace: SOLAR_WORKSPACE when it is exported, else the workspace that contains the current
# directory. Unlike `solar status`, an exported SOLAR_WORKSPACE is honoured from a directory that
# is in no workspace; it still fails when the current directory belongs to a workspace that
# disagrees with it, and when that workspace cannot be resolved (it is never guessed). The approval
# screen names the resolved workspace before the operator types yes. `--help` (also of one
# operation) needs no workspace.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVER="$SCRIPT_DIR/../../solar-paths/scripts/resolve_solar_paths.sh"
MCP_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-mcp/scripts" && pwd)"
APPROVE=("${SOLAR_MCP_PYTHON:-python3}" "$MCP_SCRIPTS/operator_approve.py")

[[ $# -gt 0 ]] || exec "${APPROVE[@]}"
for arg in "$@"; do
  [[ "$arg" == -- ]] && break      # after `--` come operands (a task id may start with `-`)
  case "$arg" in -h|--help) exec "${APPROVE[@]}" "$@" ;; esac
done

# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$RESOLVER"

if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
  # Is the current directory inside a workspace? A plain filesystem check: it says nothing about
  # whether that workspace is valid, so no error message is ever interpreted.
  if _resolve_discover >/dev/null 2>&1; then
    solar_resolve_paths --quiet                                   # same workspace passes; another one or an invalid one stops
  else
    solar_resolve_paths --workspace "$SOLAR_WORKSPACE" --quiet    # in no workspace: the variable decides
  fi
else
  solar_resolve_paths --quiet
fi

exec "${APPROVE[@]}" "$@"
