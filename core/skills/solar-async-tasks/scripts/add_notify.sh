#!/bin/bash

# Set notify_when: completed on a task.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
[[ -z "$TASK_ID" ]] && echo "Usage: $0 <task_id>" >&2 && exit 1

state task set "$TASK_ID" notify_when completed >/dev/null
echo "Task $TASK_ID will notify when completed."
