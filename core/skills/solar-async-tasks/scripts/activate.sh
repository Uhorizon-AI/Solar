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
HOOKS_RAN=0
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
            HOOKS_RAN=1
        fi
    done
fi
rm -f "$export_file"

WORKER="activate-$$"
# The claim decides. A refusal (another worker got it, or its approval does not cover
# what is stored) stops here: nothing is stamped, released or reported as activated.
if ! CLAIM_JSON="$(state task claim "$TASK_ID" --worker "$WORKER" --stamp-last-run)"; then
    # The hooks above took the task's resources. A claim that is refused (capacity, access, a
    # pending cancellation...) must not leave them held: the on_error hooks force-release them.
    if [[ "$HOOKS_RAN" == 1 ]]; then
        export_file="$(task_export_tmp "$TASK_ID")"
        for resource in $(parse_resources "$(task_field "$TASK_ID" "resources")"); do
            error_hook="$HOOKS_DIR/${resource}/on_error.sh"
            [[ -x "$error_hook" ]] && { "$error_hook" "$export_file" || true; }
        done
        rm -f "$export_file"
    fi
    REASON="$(printf '%s' "$CLAIM_JSON" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("reason") or "unknown")
except Exception: print("unknown")')"
    case "$REASON" in
        absent|legacy|mismatch)
            echo "Error: approval_digest_mismatch (reason=$REASON): the approval of $TASK_ID does not cover its current content. Approve it again with task.approve." >&2
            ;;
        global_capacity|provider_capacity|scope_conflict|resource:*|exclusive_needs_idle|blocked_by_exclusive|drain_barrier|maintenance)
            echo "Error: Task $TASK_ID cannot start now (reason=$REASON); it stays queued. Capacity, access and the execution policy are shared with the worker." >&2
            ;;
        blocked_by_dependency|cancellation_requested|parent_revoked|access_policy_invalid)
            echo "Error: Task $TASK_ID was not started (reason=$REASON); it stays queued." >&2
            ;;
        *)
            echo "Error: Task $TASK_ID was not claimed (reason=$REASON); it is no longer queued." >&2
            ;;
    esac
    exit 1
fi

# The claim stamped recurring_last_run itself (same transaction), so a failure after it
# cannot leave an active task without its interval. Do not move this stamp before the claim,
# and do not align it with start_next.sh: there the hooks run after the claim and may release
# it, here they run before it, so the claim is the first point at which a run really starts.
state task unset "$TASK_ID" blocked_by_task_ids >/dev/null

# The reservation is taken; the worker runs the task (it takes the execution over by token).
echo "✅ Activated task: [$TASK_ID] $TITLE"
