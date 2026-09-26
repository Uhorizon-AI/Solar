#!/bin/bash

# Mark a task recurring. max_runs 0 means unlimited.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
MAX_RUNS="${2:-0}"
MIN_INTERVAL="${3:-86400}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: set_recurring.sh <task_id> [max_runs] [min_interval_seconds]" >&2
    exit 1
fi

state task set "$TASK_ID" recurring true >/dev/null
state task set "$TASK_ID" recurring_max_runs "$MAX_RUNS" >/dev/null
state task set "$TASK_ID" recurring_run_count 0 >/dev/null
state task set "$TASK_ID" recurring_min_interval "$MIN_INTERVAL" >/dev/null

echo "✅ Task set as recurring: $TASK_ID"
echo "   - max_runs: $MAX_RUNS (0 = unlimited)"
echo "   - min_interval: ${MIN_INTERVAL}s"
