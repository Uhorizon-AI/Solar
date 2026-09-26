#!/bin/bash

# Park an active parent until the named children are terminal.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
shift || true

if [[ -z "$TASK_ID" || $# -eq 0 ]]; then
    echo "Usage: $0 <task_id> <child_task_id> [child_task_id...]" >&2
    exit 1
fi

cmd=(state task await "$TASK_ID")
for child in "$@"; do
    [[ -z "$child" ]] && continue
    cmd+=(--child "$child")
done

state_json="$("${cmd[@]}")"
child_csv="$(printf '%s' "$state_json" | python3 -c 'import json,sys; print("awaited")')"

echo "⏸️  Re-queued task awaiting subtasks: $TASK_ID"
echo "   blocked_by_task_ids: $(task_field "$TASK_ID" "blocked_by_task_ids")"
