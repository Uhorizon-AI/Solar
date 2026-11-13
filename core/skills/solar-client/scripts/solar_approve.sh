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
  case "$arg" in -h|--help) exec "${APPROVE[@]}" "$@" ;; esac
done

# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$RESOLVER"

if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
  # Which workspace contains the current directory? Ask the resolver without the variable.
  probe_rc=0
  probe_msg="$(env -u SOLAR_WORKSPACE bash -c 'source "$1" && solar_resolve_paths --quiet' _ "$RESOLVER" 2>&1)" \
    || probe_rc=$?
  if [[ $probe_rc -eq 0 ]]; then
    solar_resolve_paths --quiet                                   # same workspace passes; another one conflicts
  elif [[ "$probe_msg" == *"no Solar workspace found"* ]]; then
    solar_resolve_paths --workspace "$SOLAR_WORKSPACE" --quiet    # in no workspace: the variable decides
  else
    printf '%s\n' "$probe_msg" >&2                                # a workspace that cannot be resolved stops here
    exit 1
  fi
else
  solar_resolve_paths --quiet
fi

exec "${APPROVE[@]}" "$@"
