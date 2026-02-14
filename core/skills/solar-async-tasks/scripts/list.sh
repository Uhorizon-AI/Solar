#!/bin/bash

# List all tasks

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

echo "=== DRAFTS ==="
for f in "$DIR_DRAFTS"/*.md; do
    [ -e "$f" ] || continue
    ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
    TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
    echo "[$ID] $TITLE"
done

echo ""
echo "=== PLANNED ==="
for f in "$DIR_PLANNED"/*.md; do
    [ -e "$f" ] || continue
    ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
    TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
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
# Order by priority: high, normal, low; within each group by filename (timestamp)
for prio in high normal low; do
    for f in $(grep -l "priority: $prio" "$DIR_QUEUED"/*.md 2>/dev/null | sort); do
        [ -e "$f" ] || continue
        ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
        TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
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
done

echo ""
echo "=== ACTIVE ==="
for f in "$DIR_ACTIVE"/*.md; do
    [ -e "$f" ] || continue
    ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
    TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
    echo "[$ID] $TITLE"
done

echo ""
echo "=== COMPLETED (Last 5) ==="
ls -t "$DIR_COMPLETED"/*.md 2>/dev/null | head -n 5 | while read f; do
    ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
    TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
    RECURRING=$(extract_meta "$f" "recurring")
    [[ "$RECURRING" == "true" ]] && TITLE="$TITLE 🔁"
    echo "[$ID] $TITLE"
done

echo ""
echo "=== ERROR ==="
for f in "$DIR_ERROR"/*.md; do
    [ -e "$f" ] || continue
    ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
    TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
    ERROR_TIME=$(extract_meta "$f" "cleanup_error_time")
    echo "[$ID] ❌ $TITLE (error at: $ERROR_TIME)"
done

echo ""
echo "=== ARCHIVE (Last 5) ==="
ls -t "$DIR_ARCHIVE"/*.md 2>/dev/null | head -n 5 | while read f; do
    ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
    TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
    RUN_COUNT=$(extract_meta "$f" "recurring_run_count")
    [[ -n "$RUN_COUNT" ]] && TITLE="$TITLE (ran $RUN_COUNT times)"
    echo "[$ID] $TITLE"
done
