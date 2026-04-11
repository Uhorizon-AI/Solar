#!/usr/bin/env bash
# ensure_async_tasks.sh — Execution entry point for async-tasks.
#
# If solar-system is supervising async-tasks, this is a no-op.
# Otherwise it runs the local worker once as fallback.
#
# Usage:
#   bash core/skills/solar-async-tasks/scripts/ensure_async_tasks.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if bash "$SCRIPT_DIR/check_async_tasks.sh" --quiet; then
  # solar-system is supervising execution, nothing to do here.
  exit 0
fi

# Fallback: async-tasks is not supervised by solar-system, run worker directly.
echo "▶ async-tasks not supervised by solar-system, running worker fallback."
exec bash "$SCRIPT_DIR/run_worker.sh" --once
