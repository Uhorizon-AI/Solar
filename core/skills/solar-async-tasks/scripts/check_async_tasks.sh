#!/usr/bin/env bash
# check_async_tasks.sh — observe the resident async-tasks supervisor. Starts nothing.
#
# Reads the identity the supervisor publishes and proves the process behind it (pid and start
# time). It never takes the supervisor's lock, never writes a pid for it and never removes a lock.
#
# One JSON object on stdout (state, reason, identity, age_seconds, heartbeat_age_seconds). Exit codes:
#   0 ready · 10 starting · 20 blocked (maintenance, recovery, stale heartbeat, draining ...) · 1 failed
#   or not running.
#
# Usage:
#   bash core/skills/solar-async-tasks/scripts/check_async_tasks.sh [--quiet]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

if [[ -z "${SOLAR_WORKSPACE:-}" ]]; then
  _RESOLVE="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
  if [[ -f "$_RESOLVE" ]]; then
    # shellcheck source=/dev/null
    source "$_RESOLVE"
    solar_resolve_paths --quiet 2>/dev/null || true
  fi
fi

if $QUIET; then
  exec python3 "$SCRIPT_DIR/supervisor_lib.py" observe >/dev/null
fi
exec python3 "$SCRIPT_DIR/supervisor_lib.py" observe
