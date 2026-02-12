#!/bin/bash

# Start the next high-priority task (move from queued to active)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

# Priority order: high, normal, low
find_next_task() {
    # Check for high priority first
    local task=$(grep -l "priority: high" "$DIR_QUEUED"/*.md 2>/dev/null | head -n 1)
    if [ ! -z "$task" ]; then echo "$task"; return; fi

    # Check for normal priority
    task=$(grep -l "priority: normal" "$DIR_QUEUED"/*.md 2>/dev/null | head -n 1)
    if [ ! -z "$task" ]; then echo "$task"; return; fi

    # Check for low priority
    task=$(grep -l "priority: low" "$DIR_QUEUED"/*.md 2>/dev/null | head -n 1)
    if [ ! -z "$task" ]; then echo "$task"; return; fi
}

TASK_FILE=$(find_next_task)

if [ -z "$TASK_FILE" ]; then
    echo "No tasks in queue."
    exit 0
fi

TASK_ID=$(grep "^id:" "$TASK_FILE" | head -n1 | cut -d '"' -f 2)
TITLE=$(grep "^title:" "$TASK_FILE" | head -n1 | cut -d '"' -f 2)

echo "Starting task: [$TASK_ID] $TITLE"

NEW_FILE="${DIR_ACTIVE}/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"

# Update status
sed -i '' 's/^status: queued/status: active/' "$NEW_FILE"

echo "Task moved to ACTIVE."
echo "File: $NEW_FILE"
