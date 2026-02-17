#!/bin/bash

# Re-queue a task that is in error/ so it can run again (next schedule window or immediately if no schedule).
# Use after fixing the cause of the failure (env, provider, etc.).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="$1"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id>" >&2
    echo "  Moves the task from error/ to queued/ and sets status to queued." >&2
    echo "  Example: $0 0194f2f2-9b7b-7a8d-b2d7-6b4f2f0d9c31" >&2
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")
if [[ -z "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

STATUS=$(get_status "$TASK_FILE")
if [[ "$STATUS" != "error" ]]; then
    echo "Error: Task must be in error/ to requeue. Current: $STATUS" >&2
    exit 1
fi

ensure_dirs

# Update status to queued
sed -i.bak 's/^status:.*/status: queued/' "$TASK_FILE"
rm -f "${TASK_FILE}.bak"

# Remove ## Execution Error block and everything after it (clean slate for requeue)
sed -i.bak '/^## Execution Error$/,$d' "$TASK_FILE"
rm -f "${TASK_FILE}.bak"

NEW_FILE="$DIR_QUEUED/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"

echo "✅ Task $TASK_ID re-queued. File: $NEW_FILE"
echo "   It will run in the next eligible window (schedule/priority)."
