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
    echo "[$ID] $TITLE"
done

echo ""
echo "=== QUEUED ==="
# Order by priority: high, normal, low; within each group by filename (timestamp)
for prio in high normal low; do
    for f in $(grep -l "priority: $prio" "$DIR_QUEUED"/*.md 2>/dev/null | sort); do
        [ -e "$f" ] || continue
        ID=$(grep "^id:" "$f" | head -n1 | cut -d '"' -f 2)
        TITLE=$(grep "^title:" "$f" | head -n1 | cut -d '"' -f 2)
        echo "[$ID] ($prio) $TITLE"
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
    echo "[$ID] $TITLE"
done
