#!/bin/bash

# Activate one task by id.
# draft or planned becomes queued through task approve (no priority rewrite),
# then that id is claimed. Schedule and recurring gates are not applied.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id>" >&2
    echo "  Activates one specific task deterministically by ID." >&2
    exit 1
fi

if [[ $# -gt 1 ]]; then
    echo "Error: activate.sh only accepts <task_id>. Priority stays as stored." >&2
    exit 1
fi

STATUS="$(task_status_of "$TASK_ID" 2>/dev/null || true)"
if [[ -z "$STATUS" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

case "$STATUS" in
    draft|planned)
        state task approve "$TASK_ID" >/dev/null
        ;;
    queued)
        ;;
    active)
        TITLE="$(task_field "$TASK_ID" "title")"
        echo "ℹ️  Task already active: [$TASK_ID] $TITLE"
        exit 0
        ;;
    error)
        echo "Error: Task is in error. Requeue it first:" >&2
        echo "  bash core/skills/solar-async-tasks/scripts/requeue_from_error.sh $TASK_ID" >&2
        exit 1
        ;;
    completed|archived)
        echo "Error: Task is in '$STATUS' state. Duplicate or recreate it to run again." >&2
        exit 1
        ;;
    *)
        echo "Error: Unsupported task state: $STATUS" >&2
        exit 1
        ;;
esac

TITLE="$(task_field "$TASK_ID" "title")"
export_file="$(task_export_tmp "$TASK_ID")"
if [[ "$(task_field "$TASK_ID" "cleanup_required")" == "true" ]]; then
    resources="$(task_field "$TASK_ID" "resources")"
    for resource in $(parse_resources "$resources"); do
        hook="$HOOKS_DIR/${resource}/pre_start.sh"
        if [[ -x "$hook" ]]; then
            echo "Running pre-start hook for: $resource"
            if ! "$hook" "$export_file"; then
                rm -f "$export_file"
                echo "Error: pre-start hook blocked activation (resource busy): $TASK_ID" >&2
                exit 1
            fi
        fi
    done
fi
rm -f "$export_file"

if [[ "$(task_field "$TASK_ID" "recurring")" == "true" ]]; then
    state task set "$TASK_ID" recurring_last_run "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
fi

WORKER="activate-$$"
state task claim "$TASK_ID" --worker "$WORKER" >/dev/null
state task unset "$TASK_ID" blocked_by_task_ids >/dev/null

echo "✅ Activated task: [$TASK_ID] $TITLE"
