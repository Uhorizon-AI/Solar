#!/bin/bash

# Initialize the async tasks runtime environment

# Source library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

echo "Initializing Solar Async Tasks..."
echo "Root: $SOLAR_TASK_ROOT"

ensure_dirs

# Create a sample generic task if drafts is empty
if [ -z "$(ls -A "$DIR_DRAFTS")" ]; then
    echo "Creating sample draft task..."
    sample_id=$(generate_id)
    cat > "$DIR_DRAFTS/${sample_id}_sample-task.md" <<EOF
---
id: $sample_id
title: Sample Task
created: $(date -Iseconds)
status: draft
priority: normal
---

# Sample Task

This is a sample task created by setup.
EOF
fi

echo "Setup complete."
