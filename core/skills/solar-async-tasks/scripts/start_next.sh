#!/bin/bash

# Start the next high-priority task (move from queued to active)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

# Priority order: high, normal, low; only tasks that pass is_scheduled_now
find_next_task() {
    local task f
    for prio in high normal low; do
        for f in $(grep -l "priority: $prio" "$DIR_QUEUED"/*.md 2>/dev/null | sort); do
            [[ -e "$f" ]] || continue
            if is_scheduled_now "$f"; then
                echo "$f"
                return
            fi
        done
    done
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
