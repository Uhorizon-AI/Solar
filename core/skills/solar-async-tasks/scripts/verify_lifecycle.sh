#!/bin/bash

# Test script to verify solar-async-tasks functionality

set -e

# Setup
echo "Running setup..."
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
bash core/skills/solar-async-tasks/scripts/start_next.sh

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
