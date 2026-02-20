#!/bin/bash

# Activate a specific task by ID with deterministic transitions.
# Flow:
# - draft   -> planned -> queued (auto)
# - planned -> queued (auto)
# - queued  -> active  (manual activation: bypass recurring/schedule gates)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

usage() {
    echo "Usage: $0 <task_id>" >&2
    echo "  Activates one specific task deterministically by ID." >&2
    echo "  If task is draft/planned, it is auto-moved to queued first." >&2
    exit 1
}

if [[ -z "$TASK_ID" ]]; then
    usage
fi

if [[ $# -gt 1 ]]; then
    echo "Error: activate.sh only accepts <task_id>. Priority comes from task frontmatter." >&2
    exit 1
fi

ensure_dirs

TASK_FILE="$(find_task "$TASK_ID")"
if [[ -z "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

STATUS="$(get_status "$TASK_FILE")"

case "$STATUS" in
    draft)
        "$SCRIPT_DIR/plan.sh" "$TASK_ID" >/dev/null
        TASK_FILE="$(find_task "$TASK_ID")"
        APPROVE_PRIORITY="$(extract_meta "$TASK_FILE" "priority")"
        [[ -z "$APPROVE_PRIORITY" ]] && APPROVE_PRIORITY="normal"
        "$SCRIPT_DIR/approve.sh" "$TASK_ID" "$APPROVE_PRIORITY" >/dev/null
        ;;
    planned)
        APPROVE_PRIORITY="$(extract_meta "$TASK_FILE" "priority")"
        [[ -z "$APPROVE_PRIORITY" ]] && APPROVE_PRIORITY="normal"
        "$SCRIPT_DIR/approve.sh" "$TASK_ID" "$APPROVE_PRIORITY" >/dev/null
        ;;
    queued)
        ;;
    active)
        TITLE="$(extract_meta "$TASK_FILE" "title")"
        echo "ℹ️  Task already active: [$TASK_ID] $TITLE"
        echo "File: $TASK_FILE"
        exit 0
        ;;
    error)
        echo "Error: Task is in error/. Requeue it first:" >&2
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

TASK_FILE="$(find_task "$TASK_ID")"
STATUS="$(get_status "$TASK_FILE")"
if [[ "$STATUS" != "queued" ]]; then
    echo "Error: Expected queued state before activation. Current: $STATUS" >&2
    exit 1
fi

TITLE="$(extract_meta "$TASK_FILE" "title")"

cleanup_required="$(extract_meta "$TASK_FILE" "cleanup_required")"
if [[ "$cleanup_required" == "true" ]]; then
    resources="$(extract_meta "$TASK_FILE" "resources")"

    for resource in $(parse_resources "$resources"); do
        hook="$SOLAR_TASK_ROOT/hooks/${resource}/pre_start.sh"
        if [[ -x "$hook" ]]; then
            echo "Running pre-start hook for: $resource"
            if ! "$hook" "$TASK_FILE"; then
                echo "Error: pre-start hook blocked activation (resource busy): $TASK_ID" >&2
                exit 1
            fi
        fi
    done
fi

if [[ "$(extract_meta "$TASK_FILE" "recurring")" == "true" ]]; then
    sed -i.bak "/^recurring_last_run:.*/c\\
recurring_last_run: $(date -u +%Y-%m-%dT%H:%M:%SZ)
" "$TASK_FILE"
    rm -f "${TASK_FILE}.bak"
fi

NEW_FILE="$DIR_ACTIVE/$(basename "$TASK_FILE")"
mv "$TASK_FILE" "$NEW_FILE"
sed -i.bak 's/^status:.*/status: active/' "$NEW_FILE"
rm -f "${NEW_FILE}.bak"

echo "✅ Activated task: [$TASK_ID] $TITLE"
echo "File: $NEW_FILE"
