#!/bin/bash

# Plan a task (move from draft to planned)

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

if [ "$STATUS" != "draft" ]; then
    echo "Error: Task must be in 'draft' state to plan. Current state: $STATUS"
    exit 1
fi

ensure_dirs

NEW_FILE="${DIR_PLANNED}/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"

# Update status in frontmatter
sed -i '' 's/^status: draft/status: planned/' "$NEW_FILE"

# Append planning template if not exists
if ! grep -q "# Implementation Plan" "$NEW_FILE"; then
    cat >> "$NEW_FILE" <<EOF

# Implementation Plan

- [ ] Technical Design
- [ ] Dependencies
- [ ] Verification Steps

EOF
fi

echo "Task $TASK_ID moved to PLANNED."
echo "File: $NEW_FILE"
