#!/usr/bin/env bash
# stop_supervisor.sh — ask the resident supervisor to drain, and wait for it.
#
#   stop_supervisor.sh --drain [--timeout N]
#
# The supervisor is identified by its published pid and start time. It is asked (through a control
# file bound to that identity) to stop dispatching, collect its executions and close its lock when
# they end. This script waits up to N seconds (default 120) and reports what is still running.
# It never removes the lock and never kills a process: not the supervisor, not an execution.
#
# Exit codes: 0 gone and nothing pending (or none was running) · 1 still draining at the deadline ·
#             2 refused: the owner cannot be identified · 3 gone, but executions with an uncertain
#             owner or a failed cleanup remain blocked.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${SOLAR_WORKSPACE:-}" ]]; then
  _RESOLVE="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
  if [[ -f "$_RESOLVE" ]]; then
    # shellcheck source=/dev/null
    source "$_RESOLVE"
    solar_resolve_paths --quiet 2>/dev/null || true
  fi
fi

exec python3 "$SCRIPT_DIR/supervisor_lib.py" stop "$@"
