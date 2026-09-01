#!/usr/bin/env bash
# check_async_tasks.sh — Check if a run_worker.sh process is already running.
#
# Exit codes:
#   0 — worker is already running (no action needed)
#   1 — worker is not running (caller should start it)
set -euo pipefail

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

log() { $QUIET || echo "$*"; }

LOCK_FILE="${SOLAR_TASK_WORKER_LOCK:-/tmp/solar-async-tasks-worker.lock}"

# Check lock file: exists and PID is alive
if [[ -f "$LOCK_FILE" ]]; then
  existing_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    log "⏸️  run_worker.sh already running (pid=$existing_pid)."
    exit 0
  fi
  # Stale lock — clean it up
  rm -f "$LOCK_FILE"
fi

log "✅ No worker running — safe to start."
exit 1
