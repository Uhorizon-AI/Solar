#!/bin/bash

# Approve a task (move from planned to queued)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="$1"
PRIORITY="${2:-normal}"

if [ -z "$TASK_ID" ]; then
    echo "Usage: $0 <task_id> [priority: high|normal|low]"
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")

if [ -z "$TASK_FILE" ]; then
    echo "Error: Task $TASK_ID not found."
    exit 1
fi

STATUS=$(get_status "$TASK_FILE")

if [ "$STATUS" != "planned" ]; then
    echo "Error: Task must be in 'planned' state to approve. Current state: $STATUS"
    exit 1
fi

ensure_dirs

NEW_FILE="${DIR_QUEUED}/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"

# Update status and priority
sed -i '' 's/^status: planned/status: queued/' "$NEW_FILE"
sed -i '' "s/^priority: .*/priority: $PRIORITY/" "$NEW_FILE"

echo "Task $TASK_ID approved and QUEUED with priority $PRIORITY."
echo "File: $NEW_FILE"
