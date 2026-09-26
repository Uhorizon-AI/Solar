#!/bin/bash

# Finish an active task. Resource hooks run first. The status change, including
# a recurring requeue or archive, is one call to solar-state.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: complete.sh <task_id>" >&2
    exit 1
fi

STATUS="$(task_status_of "$TASK_ID" 2>/dev/null || true)"
if [[ -z "$STATUS" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi
if [[ "$STATUS" != "active" ]]; then
    echo "Error: Task $TASK_ID is '$STATUS', not active." >&2
    exit 1
fi

export_file="$(task_export_tmp "$TASK_ID")"
cleanup_required="$(task_field "$TASK_ID" "cleanup_required")"

if [[ "$cleanup_required" == "true" ]]; then
    resources="$(task_field "$TASK_ID" "resources")"
    cleanup_timeout="$(task_field "$TASK_ID" "cleanup_timeout")"
    cleanup_timeout=${cleanup_timeout:-30}
    timeout_cmd=$(get_timeout_cmd)
    cleanup_failed=false

    for resource in $(parse_resources "$resources"); do
        hook="$HOOKS_DIR/${resource}/post_complete.sh"
        if [[ -x "$hook" ]]; then
            echo "Running cleanup hook for: $resource"
            if [[ -n "$timeout_cmd" ]]; then
                if ! $timeout_cmd "$cleanup_timeout" "$hook" "$export_file"; then
                    echo "❌ Cleanup hook failed for $resource" >&2
                    cleanup_failed=true
                fi
            else
                if ! "$hook" "$export_file"; then
                    echo "❌ Cleanup hook failed for $resource" >&2
                    cleanup_failed=true
                fi
            fi
        fi
    done

    if [[ "$cleanup_failed" == "true" ]]; then
        for resource in $(parse_resources "$resources"); do
            error_hook="$HOOKS_DIR/${resource}/on_error.sh"
            if [[ -x "$error_hook" ]]; then
                echo "Running on_error hook for: $resource"
                "$error_hook" "$export_file" || true
            fi
        done
        rm -f "$export_file"
        state task fail "$TASK_ID" \
            --field cleanup_error=true \
            --field "cleanup_error_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
        bash "$SCRIPT_DIR/notify_if_configured.sh" "$TASK_ID" || true
        echo "❌ Task moved to error due to cleanup failure: $TASK_ID"
        exit 1
    fi
fi
rm -f "$export_file"

if [[ "${SOLAR_TASK_CANCELLED:-}" == "1" ]]; then
    state task complete "$TASK_ID" --cancelled >/dev/null
    exit 0
fi

landed="$(state task complete "$TASK_ID")"
status="$(printf '%s' "$landed" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"

bash "$SCRIPT_DIR/notify_if_configured.sh" "$TASK_ID" || true

case "$status" in
    archived)
        count="$(task_field "$TASK_ID" "recurring_run_count")"
        echo "✅ Recurring task archived after ${count:-?} runs: $TASK_ID"
        ;;
    queued)
        count="$(task_field "$TASK_ID" "recurring_run_count")"
        echo "✅ Recurring task re-queued (run ${count:-?}): $TASK_ID"
        ;;
    *)
        echo "✅ Task completed: $TASK_ID"
        ;;
esac
