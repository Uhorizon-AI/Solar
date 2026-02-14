#!/bin/bash

# Set cleanup configuration for a task
# Usage: set_cleanup.sh <task_id> <resources_csv> [timeout]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
RESOURCES="${2:-}"
TIMEOUT="${3:-30}"

if [[ -z "$TASK_ID" ]] || [[ -z "$RESOURCES" ]]; then
    echo "Usage: set_cleanup.sh <task_id> <resources_csv> [timeout]" >&2
    echo "Examples:" >&2
    echo "  set_cleanup.sh 20250213-090000 chrome-dev-tools          # Single resource, 30s timeout" >&2
    echo "  set_cleanup.sh 20250213-090000 chrome-dev-tools,postgres # Multiple resources" >&2
    echo "  set_cleanup.sh 20250213-090000 chrome-dev-tools 60       # Custom timeout" >&2
    exit 1
fi

TASK_FILE=$(find_task "$TASK_ID")

if [[ -z "$TASK_FILE" ]]; then
    echo "Error: Task $TASK_ID not found." >&2
    exit 1
fi

# Add/update cleanup fields
sed -i.bak '/^resources:/d' "$TASK_FILE"
sed -i.bak '/^cleanup_required:/d' "$TASK_FILE"
sed -i.bak '/^cleanup_timeout:/d' "$TASK_FILE"

# Insert before closing --- (2nd occurrence)
awk -v resources="$RESOURCES" -v timeout="$TIMEOUT" '
    /^---$/ && ++count == 2 && !done {
        print "resources: \"" resources "\""
        print "cleanup_required: true"
        print "cleanup_timeout: " timeout
        done = 1
    }
    { print }
' "$TASK_FILE" > "$TASK_FILE.tmp" && mv "$TASK_FILE.tmp" "$TASK_FILE"

rm -f "${TASK_FILE}.bak"

echo "✅ Cleanup configured: $TASK_ID"
echo "   - resources: $RESOURCES"
echo "   - timeout: ${TIMEOUT}s"
