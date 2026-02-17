#!/bin/bash

# List all tasks

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

echo "=== DRAFTS ==="
for f in "$DIR_DRAFTS"/*.md; do
    [ -e "$f" ] || continue
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    echo "[$ID] $TITLE"
done

echo ""
echo "=== PLANNED ==="
for f in "$DIR_PLANNED"/*.md; do
    [ -e "$f" ] || continue
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    STIME=$(extract_meta "$f" "scheduled_time")
    SDAYS=$(extract_meta "$f" "scheduled_weekdays")
    if [[ -n "$STIME" || -n "$SDAYS" ]]; then
        SCHED="$STIME"
        [[ -n "$SDAYS" ]] && SCHED="${SCHED:+$SCHED }$(weekdays_display "$SDAYS")"
        echo "[$ID] $TITLE @ $SCHED"
    else
        echo "[$ID] $TITLE"
    fi
done

echo ""
echo "=== QUEUED ==="
# Order by priority (high > normal > low), then created asc (FIFO)
find "$DIR_QUEUED" -name "*.md" -print 2>/dev/null | while read -r f; do
    [[ -e "$f" ]] || continue
    prio="$(extract_meta "$f" "priority")"
    prio_val=0
    [[ "$prio" == "high" ]] && prio_val=2
    [[ "$prio" == "normal" ]] && prio_val=1
    [[ "$prio" == "low" ]] && prio_val=0
    ts="$(created_epoch "$f")"
    printf '%s\t%s\t%s\t%s\n' "$prio_val" "$ts" "$prio" "$f"
done | sort -t$'\t' -k1,1nr -k2,2n | while IFS=$'\t' read -r _ _ prio f; do
    [ -e "$f" ] || continue
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    STIME=$(extract_meta "$f" "scheduled_time")
    SDAYS=$(extract_meta "$f" "scheduled_weekdays")
    RECURRING=$(extract_meta "$f" "recurring")
    CLEANUP=$(extract_meta "$f" "cleanup_required")
    RESOURCES=$(extract_meta "$f" "resources")

    # Build schedule string
    SCHED=""
    if [[ -n "$STIME" || -n "$SDAYS" ]]; then
        SCHED="$STIME"
        [[ -n "$SDAYS" ]] && SCHED="${SCHED:+$SCHED }$(weekdays_display "$SDAYS")"
        SCHED=" @ $SCHED"
    fi

    # Build tags
    TAGS=""
    [[ "$RECURRING" == "true" ]] && TAGS="${TAGS}🔁 "
    [[ "$CLEANUP" == "true" ]] && TAGS="${TAGS}🧹($RESOURCES) "

    echo "[$ID] ($prio) $TITLE$SCHED $TAGS"
done

echo ""
echo "=== ACTIVE ==="
for f in "$DIR_ACTIVE"/*.md; do
    [ -e "$f" ] || continue
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    echo "[$ID] $TITLE"
done

echo ""
echo "=== COMPLETED (Last 5) ==="
ls -t "$DIR_COMPLETED"/*.md 2>/dev/null | head -n 5 | while read f; do
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    RECURRING=$(extract_meta "$f" "recurring")
    [[ "$RECURRING" == "true" ]] && TITLE="$TITLE 🔁"
    echo "[$ID] $TITLE"
done

echo ""
echo "=== ERROR ==="
for f in "$DIR_ERROR"/*.md; do
    [ -e "$f" ] || continue
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    ERROR_TIME=$(extract_meta "$f" "cleanup_error_time")
    # Execution errors have time in body (## Execution Error - time: ...), not in frontmatter
    # Use last occurrence so requeue+refail shows most recent error time
    if [[ -z "$ERROR_TIME" ]]; then
        ERROR_TIME=$(grep "^- time:" "$f" 2>/dev/null | tail -n1 | sed 's/^- time: //' | tr -d ' ')
    fi
    echo "[$ID] ❌ $TITLE (error at: ${ERROR_TIME:-see file})"
    echo "    → Detalle: $f"
done

echo ""
echo "=== ARCHIVE (Last 5) ==="
ls -t "$DIR_ARCHIVE"/*.md 2>/dev/null | head -n 5 | while read f; do
    ID=$(extract_meta "$f" "id")
    TITLE=$(extract_meta "$f" "title")
    RUN_COUNT=$(extract_meta "$f" "recurring_run_count")
    [[ -n "$RUN_COUNT" ]] && TITLE="$TITLE (ran $RUN_COUNT times)"
    echo "[$ID] $TITLE"
done
