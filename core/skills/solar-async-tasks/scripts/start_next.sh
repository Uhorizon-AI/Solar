#!/bin/bash

# Claim the next ready task. Eligibility (priority, dependencies, schedule,
# recurring interval, a pending cancellation) is decided inside solar-state.
# Resource hooks run after the claim; a hook that blocks releases the task.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

WORKER="start-next-$$"
EXCLUDE=""

while true; do
    claimed_json="$(state task claim-next --worker "$WORKER" --exclude "$EXCLUDE")"
    TASK_ID="$(printf '%s' "$claimed_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id") or "")')"
    TITLE="$(printf '%s' "$claimed_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("title") or "")')"
    if [[ -z "$TASK_ID" ]]; then
        echo "⏸️  No tasks ready to start"
        exit 0
    fi

    export_file="$(task_export_tmp "$TASK_ID")"
    hook_failed=false
    if [[ "$(task_field "$TASK_ID" "cleanup_required")" == "true" ]]; then
        resources="$(task_field "$TASK_ID" "resources")"
        for resource in $(parse_resources "$resources"); do
            hook="$HOOKS_DIR/${resource}/pre_start.sh"
            if [[ -x "$hook" ]]; then
                echo "Running pre-start hook for: $resource"
                if ! "$hook" "$export_file"; then
                    echo "⏸️  Pre-start hook blocked task (resource busy): $TASK_ID"
                    hook_failed=true
                    break
                fi
            fi
        done
    fi
    rm -f "$export_file"

    if [[ "$hook_failed" == "true" ]]; then
        state task release "$TASK_ID" --worker "$WORKER" >/dev/null
        EXCLUDE="${EXCLUDE:+$EXCLUDE,}$TASK_ID"
        continue
    fi

    if [[ "$(task_field "$TASK_ID" "recurring")" == "true" ]]; then
        state task set "$TASK_ID" recurring_last_run "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
    fi
    state task unset "$TASK_ID" blocked_by_task_ids >/dev/null

    echo "✅ Started task: [$TASK_ID] $TITLE"
    exit 0
done
