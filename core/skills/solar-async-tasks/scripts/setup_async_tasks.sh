#!/bin/bash

# The task queue lives in solar-state. This only prepares the hook directory,
# which stays configuration under async-tasks/hooks/.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

echo "Initializing Solar Async Tasks..."
echo "Queue: solar-state (state.sqlite)"
mkdir -p "$HOOKS_DIR"
echo "Hooks: $HOOKS_DIR"
echo "Setup complete."
