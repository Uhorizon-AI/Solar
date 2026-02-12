#!/bin/bash

# Set or update scheduled_time and scheduled_weekdays for a task.
# Usage: schedule.sh <task_id> ["HH:MM"] ["1,2,3,4,5"]
# ISO weekdays: 1=Mon .. 7=Sun. Only numeric format is stored.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="$1"
STIME="$2"
SDAYS="$3"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id> [\"HH:MM\"] [\"1,2,3,4,5\"]" >&2
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")
if [[ -z "$TASK_FILE" || ! -f "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

# Update or add scheduled_time
if [[ -n "$STIME" ]]; then
    if grep -q "^scheduled_time:" "$TASK_FILE" 2>/dev/null; then
        sed -i '' "s|^scheduled_time:.*|scheduled_time: \"$STIME\"|" "$TASK_FILE"
    else
        sed -i '' '/^priority:/a\
scheduled_time: "'"$STIME"'"' "$TASK_FILE"
    fi
fi

# Update or add scheduled_weekdays
if [[ -n "$SDAYS" ]]; then
    if grep -q "^scheduled_weekdays:" "$TASK_FILE" 2>/dev/null; then
        sed -i '' "s|^scheduled_weekdays:.*|scheduled_weekdays: \"$SDAYS\"|" "$TASK_FILE"
    else
        sed -i '' '/^priority:/a\
scheduled_weekdays: "'"$SDAYS"'"' "$TASK_FILE"
    fi
fi

echo "Schedule updated: $TASK_FILE"
[[ -n "$STIME" ]] && echo "  scheduled_time: $STIME"
[[ -n "$SDAYS" ]] && echo "  scheduled_weekdays: $SDAYS"
