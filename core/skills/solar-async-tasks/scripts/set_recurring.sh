#!/bin/bash

# Set a task as recurring with optional max runs
# Usage: set_recurring.sh <task_id> [max_runs] [min_interval_seconds]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
MAX_RUNS="${2:-0}"           # Default: unlimited
MIN_INTERVAL="${3:-86400}"   # Default: 24h

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: set_recurring.sh <task_id> [max_runs] [min_interval_seconds]" >&2
    echo "Examples:" >&2
    echo "  set_recurring.sh 20250213-090000        # Unlimited runs, 24h interval" >&2
    echo "  set_recurring.sh 20250213-090000 10     # Max 10 runs, 24h interval" >&2
    echo "  set_recurring.sh 20250213-090000 0 3600 # Unlimited runs, 1h interval" >&2
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")

if [[ -z "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

# Add/update recurring fields
sed -i.bak '/^recurring:/d' "$TASK_FILE"
sed -i.bak '/^recurring_max_runs:/d' "$TASK_FILE"
sed -i.bak '/^recurring_run_count:/d' "$TASK_FILE"
sed -i.bak '/^recurring_last_run:/d' "$TASK_FILE"
sed -i.bak '/^recurring_min_interval:/d' "$TASK_FILE"

# Insert before closing --- (2nd occurrence)
awk -v max_runs="$MAX_RUNS" -v min_interval="$MIN_INTERVAL" '
    /^---$/ && ++count == 2 && !done {
        print "recurring: true"
        print "recurring_max_runs: " max_runs
        print "recurring_run_count: 0"
        print "recurring_last_run: \"\""
        print "recurring_min_interval: " min_interval
        done = 1
    }
    { print }
' "$TASK_FILE" > "$TASK_FILE.tmp" && mv "$TASK_FILE.tmp" "$TASK_FILE"

rm -f "${TASK_FILE}.bak"

echo "✅ Task set as recurring: $TASK_ID"
echo "   - max_runs: $MAX_RUNS (0 = unlimited)"
echo "   - min_interval: ${MIN_INTERVAL}s"
