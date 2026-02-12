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
    grep "^$key:" "$file" 2>/dev/null | sed "s/^$key: //" | tr -d '"' | head -n1
}

# Schedule window margin in minutes (±)
SCHEDULE_MARGIN_MIN=15

# Return 0 if task has no schedule or is within its scheduled window; 1 otherwise.
# Frontmatter: scheduled_time "HH:MM" or "HH:MM:SS", scheduled_weekdays "1,2,3,4,5" (ISO 1=Mon .. 7=Sun).
is_scheduled_now() {
    local file="$1"
    local stime sdays
    stime=$(extract_meta "$file" "scheduled_time")
    sdays=$(extract_meta "$file" "scheduled_weekdays")
    # No schedule -> always eligible
    [[ -z "$stime" && -z "$sdays" ]] && return 0
    # Weekday check: if scheduled_weekdays set, current weekday must be in list
    if [[ -n "$sdays" ]]; then
        local current_dow
        current_dow=$(date +%u)  # 1=Mon .. 7=Sun
        if ! echo ",${sdays}," | grep -q ",${current_dow},"; then
            return 1
        fi
    fi
    # If no time set, only weekday mattered (already passed)
    [[ -z "$stime" ]] && return 0
    # Time window: ±SCHEDULE_MARGIN_MIN minutes
    local sched_min now_min
    # Parse HH:MM or HH:MM:SS
    sched_min=$(echo "$stime" | awk -F: '{ print $1*60+$2 }')
    now_min=$(date +%H:%M | awk -F: '{ print $1*60+$2 }')
    local diff=$((now_min - sched_min))
    # Normalize diff to [-720, 720] for midnight wrap
    [[ $diff -gt 720 ]] && diff=$((diff - 1440))
    [[ $diff -lt -720 ]] && diff=$((diff + 1440))
    if [[ $diff -ge -$SCHEDULE_MARGIN_MIN && $diff -le $SCHEDULE_MARGIN_MIN ]]; then
        return 0
    fi
    return 1
}

# Format scheduled_weekdays for display: "1,2,3,4,5" -> "L,M,X,J,V"
weekdays_display() {
    local nums="$1"
    [[ -z "$nums" ]] && return
    local out=""
    local i
    for i in $(echo "$nums" | tr ',' ' '); do
        case "$i" in
            1) out="${out}L," ;;
            2) out="${out}M," ;;
            3) out="${out}X," ;;
            4) out="${out}J," ;;
            5) out="${out}V," ;;
            6) out="${out}S," ;;
            7) out="${out}D," ;;
            *) out="${out}${i}," ;;
        esac
    done
    echo "${out%,}"
}
