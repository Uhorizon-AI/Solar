#!/bin/bash

# Re-queue an active task until its spawned subtasks are completed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
shift || true

if [[ -z "$TASK_ID" || $# -eq 0 ]]; then
    echo "Usage: $0 <task_id> <child_task_id> [child_task_id...]" >&2
    exit 1
fi

ensure_dirs

TASK_FILE="$(find_task "$TASK_ID")"
if [[ -z "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

STATUS="$(get_status "$TASK_FILE")"
if [[ "$STATUS" != "active" ]]; then
    echo "Error: Task must be in 'active' state to await subtasks. Current: $STATUS" >&2
    exit 1
fi

child_csv="$(printf '%s\n' "$@" | awk 'NF && !seen[$0]++' | paste -sd ',' -)"
[[ -z "$child_csv" ]] && {
    echo "Error: No child task IDs provided." >&2
    exit 1
}

sed -i.bak 's/^status:.*/status: queued/' "$TASK_FILE"
rm -f "${TASK_FILE}.bak"

if grep -q '^blocked_by_task_ids:' "$TASK_FILE"; then
    sed -i.bak "/^blocked_by_task_ids:.*/c\\
blocked_by_task_ids: \"$child_csv\"
" "$TASK_FILE"
    rm -f "${TASK_FILE}.bak"
else
    awk -v child_csv="$child_csv" '
        /^---$/ && ++count == 2 && !done {
            print "blocked_by_task_ids: \"" child_csv "\""
            done = 1
        }
        { print }
    ' "$TASK_FILE" > "$TASK_FILE.tmp" && mv "$TASK_FILE.tmp" "$TASK_FILE"
fi

NEW_FILE="$DIR_QUEUED/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"

echo "⏸️  Re-queued task awaiting subtasks: $TASK_ID"
echo "   blocked_by_task_ids: $child_csv"
echo "   File: $NEW_FILE"
