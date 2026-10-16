#!/usr/bin/env bash
# ensure_async_tasks.sh — make sure the resident async-tasks supervisor of this runtime is running.
#
# It does not run tasks and it never waits for them. It observes the supervisor's identity (it does
# not take its lock and does not write its pid), starts one candidate through launch_supervisor.sh
# when none is alive, and waits at most 5 seconds for the handshake (lock held, workspace/runtime
# identity, pid and start time, heartbeat, reconciliation done).
#
# One JSON object on the last line of stdout: state, reason, identity, age_seconds, ...
# Exit codes:
#   0   ready     the supervisor answered the handshake
#   10  starting  a live, identified process is still reconciling (the next tick sees the same one)
#   20  blocked   needs attention: maintenance, recovery, stale heartbeat, no live identity after the
#                 handshake budget, or starting for more than 120 seconds. Nothing is started again.
#   1   failed    the start failed (checked); the next tick tries again
#
# Called by:
#   - solar-system (run_orchestrator.sh) on each LaunchAgent tick
#   - an AI agent as the documented fallback when solar-system is not installed (once; it respects
#     10 and 20 and never starts run_worker.sh or another launcher)
#
# Usage:
#   bash core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh
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

exec python3 "$SCRIPT_DIR/supervisor_lib.py" ensure
