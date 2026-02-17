#!/bin/bash

# Start the next task from queue (supports recurring, scheduling, resource locks)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

# Get all queued tasks sorted by priority (high > normal > low)
QUEUED_TASKS=$(find "$DIR_QUEUED" -name "*.md" 2>/dev/null | while read -r f; do
    [[ -e "$f" ]] || continue
    prio=$(extract_meta "$f" "priority")
    prio_val=0
    [[ "$prio" == "high" ]] && prio_val=2
    [[ "$prio" == "normal" ]] && prio_val=1
    [[ "$prio" == "low" ]] && prio_val=0
    ts="$(created_epoch "$f")"
    # Sort key: priority desc, created asc (FIFO)
    printf '%s\t%s\t%s\n' "$prio_val" "$ts" "$f"
done | sort -t$'\t' -k1,1nr -k2,2n | awk -F'\t' '{print $3}')

# Try each task in order until one can start
for NEXT_TASK in $QUEUED_TASKS; do
    [[ -e "$NEXT_TASK" ]] || continue

    TASK_ID=$(extract_meta "$NEXT_TASK" "id")
    TITLE=$(extract_meta "$NEXT_TASK" "title")

    # Check recurring ready (race protection)
    if ! is_recurring_ready "$NEXT_TASK"; then
        echo "⏸️  Skipping recurring task (min_interval not elapsed): $TASK_ID"
        continue
    fi

    # Check schedule (timezone support in Phase 2 - use is_scheduled_now_tz when implemented)
    if ! is_scheduled_now "$NEXT_TASK"; then
        echo "⏸️  Skipping scheduled task (not in window): $TASK_ID"
        continue
    fi

    # Try pre-start hooks (e.g., acquire resource locks)
    cleanup_required=$(extract_meta "$NEXT_TASK" "cleanup_required")
    hook_failed=false

    if [[ "$cleanup_required" == "true" ]]; then
        resources=$(extract_meta "$NEXT_TASK" "resources")

        for resource in $(parse_resources "$resources"); do
            hook="$SOLAR_TASK_ROOT/hooks/${resource}/pre_start.sh"
            if [[ -x "$hook" ]]; then
                echo "Running pre-start hook for: $resource"
                if ! "$hook" "$NEXT_TASK"; then
                    echo "⏸️  Pre-start hook blocked task (resource busy): $TASK_ID"
                    hook_failed=true
                    break
                fi
            fi
        done
    fi

    # If hook failed, try next task in queue (avoid head-of-line blocking)
    if [[ "$hook_failed" == "true" ]]; then
        continue
    fi

    # Task can start! Update recurring_last_run if needed
    if [[ "$(extract_meta "$NEXT_TASK" "recurring")" == "true" ]]; then
        sed -i.bak "/^recurring_last_run:.*/c\\
recurring_last_run: $(date -u +%Y-%m-%dT%H:%M:%SZ)
" "$NEXT_TASK"
        rm -f "${NEXT_TASK}.bak"
    fi

    # Move to active
    NEW_FILE="$DIR_ACTIVE/$(basename "$NEXT_TASK")"
    mv "$NEXT_TASK" "$NEW_FILE"

    # Update status
    sed -i.bak 's/^status:.*/status: active/' "$NEW_FILE"
    rm -f "${NEW_FILE}.bak"

    echo "✅ Started task: [$TASK_ID] $TITLE"
    echo "File: $NEW_FILE"
    exit 0
done

# No tasks available to start
echo "⏸️  No tasks ready to start"
exit 0
