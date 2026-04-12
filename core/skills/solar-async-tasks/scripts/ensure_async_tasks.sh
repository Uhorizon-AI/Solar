#!/usr/bin/env bash
# ensure_async_tasks.sh — Ensure run_worker.sh runs exactly once at a time.
#
# If a worker is already running, this is a no-op.
# Otherwise, starts run_worker.sh --once and tracks its PID.
#
# Called by:
#   - solar-system (run_orchestrator.sh) on each LaunchAgent tick
#   - AI agent as fallback when solar-system is not installed
#
# Usage:
#   bash core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOCK_FILE="${SOLAR_TASK_WORKER_LOCK:-/tmp/solar-async-tasks-worker.lock}"

if bash "$SCRIPT_DIR/check_async_tasks.sh" --quiet; then
  # Worker already running — nothing to do.
  exit 0
fi

# Write PID lock and run worker.
echo "$$" > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT INT TERM

exec bash "$SCRIPT_DIR/run_worker.sh" --once
