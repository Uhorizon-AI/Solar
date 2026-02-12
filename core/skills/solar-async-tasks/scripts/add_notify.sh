#!/bin/bash

# Add notify_when: completed to a task so the user gets notified (e.g. via Telegram) when it completes.
# Usage: add_notify.sh <task_id>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="$1"
[[ -z "$TASK_ID" ]] && echo "Usage: $0 <task_id>" >&2 && exit 1

TASK_FILE=$(find_task "$TASK_ID")
[[ -z "$TASK_FILE" || ! -f "$TASK_FILE" ]] && echo "Error: Task $TASK_ID not found." >&2 && exit 1

if grep -q "^notify_when:" "$TASK_FILE" 2>/dev/null; then
  sed -i '' 's/^notify_when:.*/notify_when: completed/' "$TASK_FILE"
else
  sed -i '' '/^priority:/a\
notify_when: completed
' "$TASK_FILE"
fi

echo "Task $TASK_ID will notify when completed."
