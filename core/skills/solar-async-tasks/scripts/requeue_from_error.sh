#!/bin/bash

# error -> queued, dropping the execution-error section. solar-state does both.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id>" >&2
    exit 1
fi

state task requeue "$TASK_ID" >/dev/null
echo "✅ Task $TASK_ID re-queued."
echo "   It will run in the next eligible window (schedule/priority)."
