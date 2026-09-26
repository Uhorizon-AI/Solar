#!/bin/bash

# draft or planned -> queued. Does not rewrite priority.
# Activate and MCP do not call this script; they call the same verb directly.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id>" >&2
    exit 1
fi

state task approve "$TASK_ID" >/dev/null
echo "Task $TASK_ID approved and queued."
