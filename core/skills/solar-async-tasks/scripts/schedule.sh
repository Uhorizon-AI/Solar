#!/bin/bash

# Set scheduled_time and scheduled_weekdays. ISO weekdays: 1=Mon .. 7=Sun.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
STIME="${2:-}"
SDAYS="${3:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id> [\"HH:MM\"] [\"1,2,3,4,5\"]" >&2
    exit 1
fi

if [[ -n "$STIME" ]]; then
    state task set "$TASK_ID" scheduled_time "$STIME" >/dev/null
fi
if [[ -n "$SDAYS" ]]; then
    state task set "$TASK_ID" scheduled_weekdays "$SDAYS" >/dev/null
fi

echo "Schedule updated: $TASK_ID"
[[ -n "$STIME" ]] && echo "  scheduled_time: $STIME"
[[ -n "$SDAYS" ]] && echo "  scheduled_weekdays: $SDAYS"
