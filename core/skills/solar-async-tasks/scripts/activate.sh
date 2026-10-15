#!/bin/bash

# Activate one task by id.
# draft or planned becomes queued through task approve (no priority rewrite),
# then that id is claimed. Schedule and recurring gates are not applied; the
# approval digest is. A claim that is refused fails the script.

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

WORKER="activate-$$"
# The claim decides. A refusal (another worker got it, or its approval does not cover
# what is stored) stops here: nothing is stamped, released or reported as activated.
if ! CLAIM_JSON="$(state task claim "$TASK_ID" --worker "$WORKER" --stamp-last-run)"; then
    REASON="$(printf '%s' "$CLAIM_JSON" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("reason") or "unknown")
except Exception: print("unknown")')"
    case "$REASON" in
        absent|legacy|mismatch)
            echo "Error: approval_digest_mismatch (reason=$REASON): the approval of $TASK_ID does not cover its current content. Approve it again with task.approve." >&2
            ;;
        *)
            echo "Error: Task $TASK_ID was not claimed (reason=$REASON); it is no longer queued." >&2
            ;;
    esac
    exit 1
fi

# The claim stamped recurring_last_run itself (same transaction), so a failure after it
# cannot leave an active task without its interval.
state task unset "$TASK_ID" blocked_by_task_ids >/dev/null

echo "✅ Activated task: [$TASK_ID] $TITLE"
