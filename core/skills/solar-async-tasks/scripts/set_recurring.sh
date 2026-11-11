#!/bin/bash

# Mark a task recurring. max_runs 0 means unlimited.
# A recurring task needs a schedule (scheduled_time, plus scheduled_timezone): its
# occurrences keep one run from repeating. Set it first with `task.schedule`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
MAX_RUNS="${2:-0}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: set_recurring.sh <task_id> [max_runs]" >&2
    exit 1
fi

SCHEDULED_TIME="$(task_field "$TASK_ID" "scheduled_time")"
SCHEDULED_TIMEZONE="$(task_field "$TASK_ID" "scheduled_timezone")"
if [[ ! "$SCHEDULED_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ || -z "$SCHEDULED_TIMEZONE" ]]; then
    echo "A recurring task needs a schedule: set scheduled_time (HH:MM, 00:00-23:59) and scheduled_timezone with task.schedule first." >&2
    exit 1
fi

state task set "$TASK_ID" recurring true >/dev/null
state task set "$TASK_ID" recurring_max_runs "$MAX_RUNS" >/dev/null
state task set "$TASK_ID" recurring_run_count 0 >/dev/null

echo "✅ Task set as recurring: $TASK_ID"
echo "   - max_runs: $MAX_RUNS (0 = unlimited)"
echo "   - schedule: $SCHEDULED_TIME"
