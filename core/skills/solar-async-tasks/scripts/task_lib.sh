#!/bin/bash

# Shared library for solar-async-tasks
# Sourced by other scripts

# Default Root
export SOLAR_TASK_ROOT="${SOLAR_TASK_ROOT:-$HOME/Sites/solar.ai/sun/runtime/async-tasks}"

# Subdirectories
export DIR_DRAFTS="$SOLAR_TASK_ROOT/drafts"
export DIR_PLANNED="$SOLAR_TASK_ROOT/planned"
export DIR_QUEUED="$SOLAR_TASK_ROOT/queued"
export DIR_ACTIVE="$SOLAR_TASK_ROOT/active"
export DIR_COMPLETED="$SOLAR_TASK_ROOT/completed"
export DIR_ARCHIVE="$SOLAR_TASK_ROOT/archive"

# Ensure directories exist
ensure_dirs() {
    mkdir -p "$DIR_DRAFTS" "$DIR_PLANNED" "$DIR_QUEUED" "$DIR_ACTIVE" "$DIR_COMPLETED" "$DIR_ARCHIVE"
}

# Generate a unique task ID
generate_id() {
    # Format: YYYYMMDD-HHMMSS-RAND
    date +"%Y%m%d-%H%M%S-$((RANDOM % 1000))"
}

# Log a message
log_msg() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Find a task file by ID in all directories
find_task() {
    local task_id="$1"
    find "$SOLAR_TASK_ROOT" -name "*${task_id}*.md" -print -quit
}

# Get task status from file path
get_status() {
    local file_path="$1"
    if [[ "$file_path" == *"/drafts/"* ]]; then echo "draft"; fi
    if [[ "$file_path" == *"/planned/"* ]]; then echo "planned"; fi
    if [[ "$file_path" == *"/queued/"* ]]; then echo "queued"; fi
    if [[ "$file_path" == *"/active/"* ]]; then echo "active"; fi
    if [[ "$file_path" == *"/completed/"* ]]; then echo "completed"; fi
}

# Extract metadata from frontmatter
extract_meta() {
    local file="$1"
    local key="$2"
    grep "^$key:" "$file" | sed "s/^$key: //" | tr -d '"'
}
