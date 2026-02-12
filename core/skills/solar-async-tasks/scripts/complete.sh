#!/bin/bash

# Complete a task (move from active to completed)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="$1"

if [ -z "$TASK_ID" ]; then
    echo "Usage: $0 <task_id>"
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")

if [ -z "$TASK_FILE" ]; then
    echo "Error: Task $TASK_ID not found."
    exit 1
fi

STATUS=$(get_status "$TASK_FILE")

if [ "$STATUS" != "active" ]; then
    echo "Warning: Completing task from state '$STATUS' (normally 'active')."
fi

ensure_dirs

NEW_FILE="${DIR_COMPLETED}/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"

# Update status
sed -i '' "s/^status: .*/status: completed/" "$NEW_FILE"

# Add completion timestamp if not exists
if ! grep -q "^completed_at:" "$NEW_FILE"; then
    sed -i '' "/^status: completed/a\\
completed_at: \"$(date -Iseconds)\"
" "$NEW_FILE"
fi

# Optional: notify via Telegram if task has notify_when: completed and prefs have telegram_chat_id
[[ -x "$SCRIPT_DIR/notify_if_configured.sh" ]] && "$SCRIPT_DIR/notify_if_configured.sh" "$NEW_FILE" || true

echo "Task $TASK_ID COMPLETED."
echo "File: $NEW_FILE"
