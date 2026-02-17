#!/bin/bash

# Test script to verify solar-async-tasks functionality

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

# Isolate this verification from real runtime data.
TMP_ROOT="$(mktemp -d /tmp/solar-async-tasks-verify.XXXXXX)"
export SOLAR_TASK_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

# Setup
echo "Running setup in isolated root: $SOLAR_TASK_ROOT"
bash core/skills/solar-async-tasks/scripts/setup_async_tasks.sh

# Create
echo "Creating task..."
OUTPUT=$(bash core/skills/solar-async-tasks/scripts/create.sh "Test Task" "Description")
echo "$OUTPUT"
TASK_ID=$(echo "$OUTPUT" | grep "ID:" | cut -d ' ' -f 2)

if [ -z "$TASK_ID" ]; then
    echo "Failed to create task"
    exit 1
fi

# List drafts
echo "Listing drafts..."
bash core/skills/solar-async-tasks/scripts/list.sh | grep "$TASK_ID"

# Plan
echo "Planning task..."
bash core/skills/solar-async-tasks/scripts/plan.sh "$TASK_ID"

# Approve
echo "Approving task (High Priority)..."
bash core/skills/solar-async-tasks/scripts/approve.sh "$TASK_ID" high

# List queued
echo "Listing queued..."
bash core/skills/solar-async-tasks/scripts/list.sh | grep "$TASK_ID"

# Start
echo "Starting task..."
START_OUT="$(bash core/skills/solar-async-tasks/scripts/start_next.sh)"
echo "$START_OUT"
if ! echo "$START_OUT" | grep -q "Started task: \\[$TASK_ID\\]"; then
    echo "Failed: start_next.sh did not activate expected task $TASK_ID"
    exit 1
fi

# List active
echo "Listing active..."
bash core/skills/solar-async-tasks/scripts/list.sh | grep "$TASK_ID"

# Complete
echo "Completing task..."
bash core/skills/solar-async-tasks/scripts/complete.sh "$TASK_ID"

# List completed
echo "Listing completed..."
bash core/skills/solar-async-tasks/scripts/list.sh | grep "$TASK_ID"

echo "Full lifecycle test PASSED."
