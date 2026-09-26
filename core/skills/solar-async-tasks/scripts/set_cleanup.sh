#!/bin/bash

# Record the resources a task must lock, and the cleanup timeout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
RESOURCES="${2:-}"
TIMEOUT="${3:-30}"

if [[ -z "$TASK_ID" || -z "$RESOURCES" ]]; then
    echo "Usage: set_cleanup.sh <task_id> <resources_csv> [timeout]" >&2
    exit 1
fi

state task set "$TASK_ID" resources "$RESOURCES" >/dev/null
state task set "$TASK_ID" cleanup_required true >/dev/null
state task set "$TASK_ID" cleanup_timeout "$TIMEOUT" >/dev/null

echo "✅ Cleanup configured: $TASK_ID"
echo "   - resources: $RESOURCES"
echo "   - timeout: ${TIMEOUT}s"
