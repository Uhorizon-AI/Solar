#!/bin/bash

# Complete a task (move from active to completed, handle cleanup + recurring)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: complete.sh <task_id>" >&2
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")

if [[ -z "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

STATUS=$(get_status "$TASK_FILE")

if [[ "$STATUS" != "active" ]]; then
    log_msg "Warning: Completing task from state '$STATUS' (normally 'active')."
fi

# 1. Run cleanup hooks FIRST (before moving file)
cleanup_required=$(extract_meta "$TASK_FILE" "cleanup_required")

if [[ "$cleanup_required" == "true" ]]; then
    resources=$(extract_meta "$TASK_FILE" "resources")
    cleanup_timeout=$(extract_meta "$TASK_FILE" "cleanup_timeout")
    cleanup_timeout=${cleanup_timeout:-30}
    timeout_cmd=$(get_timeout_cmd)

    cleanup_failed=false

    for resource in $(parse_resources "$resources"); do
        hook="$SOLAR_TASK_ROOT/hooks/${resource}/post_complete.sh"
        if [[ -x "$hook" ]]; then
            echo "Running cleanup hook for: $resource"
            if [[ -n "$timeout_cmd" ]]; then
                if ! $timeout_cmd "$cleanup_timeout" "$hook" "$TASK_FILE"; then
                    echo "❌ Cleanup hook failed for $resource" >&2
                    cleanup_failed=true
                fi
            else
                if ! "$hook" "$TASK_FILE"; then
                    echo "❌ Cleanup hook failed for $resource" >&2
                    cleanup_failed=true
                fi
            fi
        fi
    done

    # Per MEMORY.md: block on cleanup failure → run on_error hooks + move to error/
    if [[ "$cleanup_failed" == "true" ]]; then
        # Run on_error hooks for emergency cleanup
        for resource in $(parse_resources "$resources"); do
            error_hook="$SOLAR_TASK_ROOT/hooks/${resource}/on_error.sh"
            if [[ -x "$error_hook" ]]; then
                echo "Running on_error hook for: $resource"
                "$error_hook" "$TASK_FILE" || true  # Don't fail if error hook fails
            fi
        done

        ensure_dirs
        ERROR_FILE="$DIR_ERROR/$(basename "$TASK_FILE")"

        # Update status and add error metadata
        sed -i.bak 's/^status:.*/status: error/' "$TASK_FILE"
        if ! grep -q "^cleanup_error:" "$TASK_FILE"; then
            # Insert before closing --- (2nd occurrence)
            awk -v error_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
                /^---$/ && ++count == 2 && !done {
                    print "cleanup_error: true"
                    print "cleanup_error_time: " error_time
                    done = 1
                }
                { print }
            ' "$TASK_FILE" > "$TASK_FILE.tmp" && mv "$TASK_FILE.tmp" "$TASK_FILE"
        fi

        mv "$TASK_FILE" "$ERROR_FILE"
        rm -f "${TASK_FILE}.bak"
        echo "❌ Task moved to error/ due to cleanup failure: $TASK_ID"
        exit 1
    fi
fi

# 2. Move to completed/
ensure_dirs
NEW_FILE="$DIR_COMPLETED/$(basename "$TASK_FILE")"

# Update status and timestamp (always refresh completed_at for recurring)
sed -i.bak 's/^status:.*/status: completed/' "$TASK_FILE"
sed -i.bak '/^completed_at:/d' "$TASK_FILE"  # Remove old timestamp

# Insert before closing --- (2nd occurrence)
awk -v completed_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
    /^---$/ && ++count == 2 && !done {
        print "completed_at: " completed_time
        done = 1
    }
    { print }
' "$TASK_FILE" > "$TASK_FILE.tmp" && mv "$TASK_FILE.tmp" "$TASK_FILE"

mv "$TASK_FILE" "$NEW_FILE"
rm -f "${TASK_FILE}.bak"

# Optional: notify via Telegram if configured
[[ -x "$SCRIPT_DIR/notify_if_configured.sh" ]] && "$SCRIPT_DIR/notify_if_configured.sh" "$NEW_FILE" || true

# 3. Check if recurring
recurring=$(extract_meta "$NEW_FILE" "recurring")

if [[ "$recurring" == "true" ]]; then
    recurring_max_runs=$(extract_meta "$NEW_FILE" "recurring_max_runs")
    recurring_run_count=$(extract_meta "$NEW_FILE" "recurring_run_count")

    recurring_max_runs=${recurring_max_runs:-0}
    recurring_run_count=${recurring_run_count:-0}
    recurring_run_count=$((recurring_run_count + 1))

    # Check if max runs reached
    if [[ $recurring_max_runs -gt 0 ]] && [[ $recurring_run_count -ge $recurring_max_runs ]]; then
        # Archive task (finished all runs)
        ARCHIVE_FILE="$DIR_ARCHIVE/$(basename "$NEW_FILE")"

        sed -i.bak 's/^status:.*/status: archived/' "$NEW_FILE"
        sed -i.bak "/^recurring_run_count:.*/c\\
recurring_run_count: $recurring_run_count
" "$NEW_FILE"

        mv "$NEW_FILE" "$ARCHIVE_FILE"
        rm -f "${NEW_FILE}.bak"
        echo "✅ Recurring task archived after $recurring_run_count runs: $TASK_ID"
    else
        # Re-queue task
        QUEUED_FILE="$DIR_QUEUED/$(basename "$NEW_FILE")"

        # Update metadata
        sed -i.bak 's/^status:.*/status: queued/' "$NEW_FILE"
        sed -i.bak "/^recurring_run_count:.*/c\\
recurring_run_count: $recurring_run_count
" "$NEW_FILE"

        mv "$NEW_FILE" "$QUEUED_FILE"
        rm -f "${NEW_FILE}.bak"
        echo "✅ Recurring task re-queued (run $recurring_run_count): $TASK_ID"
    fi
else
    echo "✅ Task completed: $TASK_ID"
fi
