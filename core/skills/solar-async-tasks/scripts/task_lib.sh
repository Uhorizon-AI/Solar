#!/bin/bash

# Shared library for solar-async-tasks
# Sourced by other scripts

# NOTE: Worker inherits SOLAR_WORKSPACE from parent caller; skip re-discovery when set.
# CLI and sync paths always run discovery (resolve_solar_paths.sh). Intentional exception.
if [[ -z "${SOLAR_WORKSPACE:-}" ]]; then
  _TASK_RESOLVE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-client/scripts" && pwd)/resolve_solar_paths.sh"
  if [[ -f "$_TASK_RESOLVE_SCRIPT" ]]; then
    # shellcheck source=/dev/null
    source "$_TASK_RESOLVE_SCRIPT"
    solar_resolve_paths --quiet 2>/dev/null || true
  fi
fi

if [[ -z "${SOLAR_TASK_ROOT:-}" ]]; then
  if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
    export SOLAR_TASK_ROOT="$SOLAR_WORKSPACE/sun/runtime/async-tasks"
  elif [[ -d "$(pwd)/sun/runtime/async-tasks" ]]; then
    export SOLAR_TASK_ROOT="$(pwd)/sun/runtime/async-tasks"
  else
    export SOLAR_TASK_ROOT="${HOME:-}/Sites/solar.ai/sun/runtime/async-tasks"
  fi
else
  export SOLAR_TASK_ROOT
fi

# Subdirectories
export DIR_DRAFTS="$SOLAR_TASK_ROOT/drafts"
export DIR_PLANNED="$SOLAR_TASK_ROOT/planned"
export DIR_QUEUED="$SOLAR_TASK_ROOT/queued"
export DIR_ACTIVE="$SOLAR_TASK_ROOT/active"
export DIR_COMPLETED="$SOLAR_TASK_ROOT/completed"
export DIR_ERROR="$SOLAR_TASK_ROOT/error"
export DIR_ARCHIVE="$SOLAR_TASK_ROOT/archive"
export DIR_LOCKS="$SOLAR_TASK_ROOT/.locks"

# Ensure directories exist
ensure_dirs() {
    mkdir -p "$DIR_DRAFTS" "$DIR_PLANNED" "$DIR_QUEUED" "$DIR_ACTIVE" "$DIR_COMPLETED" "$DIR_ERROR" "$DIR_ARCHIVE" "$DIR_LOCKS"
}

# Setup logging directory: flat logs/ (one .log file per task, same name as task .md).
setup_logging() {
    export LOG_DIR="${SOLAR_TASK_ROOT}/logs"
    mkdir -p "$LOG_DIR"
}

# Remove log files older than 7 days to avoid unused files piling up.
# Safe to call at start of worker/execute_active; uses find -mtime +7.
cleanup_old_logs() {
    [[ ! -d "$SOLAR_TASK_ROOT/logs" ]] && return 0
    local removed
    removed=$(find "$SOLAR_TASK_ROOT/logs" -maxdepth 1 -type f -name '*.log' -mtime +7 -print -delete 2>/dev/null | wc -l | tr -d ' ')
    if [[ -n "$removed" && "$removed" -gt 0 ]]; then
        log_msg "Cleaned $removed log(s) older than 7 days"
    fi
}

# Generate a unique task ID (UUID).
generate_id() {
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen | tr '[:upper:]' '[:lower:]'
        return 0
    fi
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 16 | sed 's/^\(........\)\(....\)\(....\)\(....\)\(............\)$/\1-\2-\3-\4-\5/'
        return 0
    fi
    # Last resort: timestamp + pid (keeps runtime functional if uuid tools are unavailable)
    printf "fallback-%s-%s\n" "$(date +%s)" "$$"
}

slugify() {
    local raw="$1"
    local slug
    slug=$(printf "%s" "$raw" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
    if [[ -z "$slug" ]]; then
        slug="task"
    fi
    printf "%s" "$slug"
}

build_task_filename() {
    local dir="$1"
    local title="$2"
    local slug candidate n
    slug="$(slugify "$title")"
    candidate="$slug"
    n=1

    while task_basename_exists "$candidate"; do
        n=$((n + 1))
        candidate="${slug}-${n}"
    done

    printf "%s/%s.md" "$dir" "$candidate"
}

task_basename_exists() {
    local base="$1"
    local logs_dir="$SOLAR_TASK_ROOT/logs"
    local d

    for d in "$DIR_DRAFTS" "$DIR_PLANNED" "$DIR_QUEUED" "$DIR_ACTIVE" "$DIR_COMPLETED" "$DIR_ERROR" "$DIR_ARCHIVE"; do
        [[ -e "$d/$base.md" ]] && return 0
    done

    [[ -e "$logs_dir/$base.log" ]] && return 0
    return 1
}

# Log a message
log_msg() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Find a task file by ID in all directories
find_task() {
    local task_id="$1"
    local f id
    for f in "$DIR_DRAFTS"/*.md "$DIR_PLANNED"/*.md "$DIR_QUEUED"/*.md "$DIR_ACTIVE"/*.md "$DIR_COMPLETED"/*.md "$DIR_ERROR"/*.md "$DIR_ARCHIVE"/*.md; do
        [[ -e "$f" ]] || continue
        id="$(extract_meta "$f" "id")"
        if [[ "$id" == "$task_id" ]]; then
            echo "$f"
            break
        fi
    done
    return 0
}

# Get task status from file path
get_status() {
    local file_path="$1"
    if [[ "$file_path" == *"/drafts/"* ]]; then echo "draft"; fi
    if [[ "$file_path" == *"/planned/"* ]]; then echo "planned"; fi
    if [[ "$file_path" == *"/queued/"* ]]; then echo "queued"; fi
    if [[ "$file_path" == *"/active/"* ]]; then echo "active"; fi
    if [[ "$file_path" == *"/completed/"* ]]; then echo "completed"; fi
    if [[ "$file_path" == *"/error/"* ]]; then echo "error"; fi
    if [[ "$file_path" == *"/archive/"* ]]; then echo "archived"; fi
}

# Extract metadata from frontmatter
# When key is missing, return empty string and exit 0 (avoids pipefail exit in callers)
extract_meta() {
    local file="$1"
    local key="$2"
    ( grep "^$key:" "$file" 2>/dev/null || true ) | sed "s/^$key: //" | tr -d '"' | head -n1
}

# Insert or replace a YAML frontmatter key (before the closing ---).
upsert_frontmatter_key() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp
    [[ -f "$file" ]] || return 1
    if grep -q "^${key}:" "$file" 2>/dev/null; then
        tmp="${file}.meta.tmp"
        awk -v k="$key" -v v="$value" '
            BEGIN { done=0 }
            $0 ~ "^" k ":" && !done { print k ": " v; done=1; next }
            { print }
        ' "$file" >"$tmp" && mv "$tmp" "$file"
        return 0
    fi
    awk -v k="$key" -v v="$value" '
        /^---$/ && ++count == 2 && !done {
            print k ": " v
            done = 1
        }
        { print }
    ' "$file" >"${file}.meta.tmp" && mv "${file}.meta.tmp" "$file"
}

telegram_chat_allowed() {
    local chat_id="$1"
    local allowed default part
    [[ -n "$chat_id" ]] || return 1
    allowed="${TELEGRAM_ALLOWED_CHAT_IDS:-}"
    if [[ -n "$allowed" ]]; then
        IFS=',' read -r -a parts <<<"$allowed"
        for part in "${parts[@]}"; do
            part="${part#"${part%%[![:space:]]*}"}"
            part="${part%"${part##*[![:space:]]}"}"
            [[ "$part" == "$chat_id" ]] && return 0
        done
        return 1
    fi
    default="${TELEGRAM_CHAT_ID:-}"
    [[ -n "$default" && "$default" == "$chat_id" ]]
}

# Brief location/URL for completion notify (frontmatter or first path/URL in ## Result).
task_result_location() {
    local file="$1"
    local loc line in_result=0
    loc="$(extract_meta "$file" "result_url")"
    [[ -n "$loc" ]] && { printf '%s\n' "$loc"; return 0; }
    loc="$(extract_meta "$file" "result_path")"
    [[ -n "$loc" ]] && { printf '%s\n' "$loc"; return 0; }
    while IFS= read -r line; do
        if [[ "$line" == "## Result"* ]]; then
            in_result=1
            continue
        fi
        if [[ "$in_result" -eq 1 && "$line" == "## "* ]]; then
            break
        fi
        if [[ "$in_result" -eq 1 ]]; then
            if printf '%s' "$line" | grep -Eo 'https?://[^[:space:])]+' >/dev/null 2>&1; then
                printf '%s\n' "$(printf '%s' "$line" | grep -Eo 'https?://[^[:space:])]+' | head -n1)"
                return 0
            fi
            if printf '%s' "$line" | grep -Eo '`[^`]+`' >/dev/null 2>&1; then
                printf '%s\n' "$(printf '%s' "$line" | grep -Eo '`[^`]+`' | head -n1 | tr -d '`')"
                return 0
            fi
        fi
    done <"$file"
    printf '%s\n' "$file"
}

# Extract created timestamp as epoch for sorting
# Tries ISO8601 parsing, falls back to file mtime
created_epoch() {
    local file="$1"
    local created created_norm ts=""

    created="$(extract_meta "$file" "created")"
    if [[ -n "$created" ]]; then
        # Normalize ISO8601 offset for BSD date: +01:00 -> +0100
        created_norm="$(echo "$created" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/')"

        # macOS/BSD date
        ts="$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "$created_norm" +%s 2>/dev/null || true)"
        if [[ -z "$ts" ]]; then
            ts="$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$created" +%s 2>/dev/null || true)"
        fi
        # GNU date fallback
        if [[ -z "$ts" ]] && command -v gdate >/dev/null 2>&1; then
            ts="$(gdate -d "$created" +%s 2>/dev/null || true)"
        elif [[ -z "$ts" ]] && date -d "1970-01-01" +%s >/dev/null 2>&1; then
            ts="$(date -d "$created" +%s 2>/dev/null || true)"
        fi
    fi

    if [[ -z "$ts" ]]; then
        # Fallback to file mtime
        ts="$(stat -f %m "$file" 2>/dev/null || echo 0)"
    fi
    echo "$ts"
}

# Return scheduled_time as minutes since midnight for sorting (HH:MM or HH:MM:SS).
# No schedule -> 9999 so unscheduled tasks sort after scheduled ones.
scheduled_minutes() {
    local file="$1"
    local stime
    stime="$(extract_meta "$file" "scheduled_time")"
    if [[ -z "$stime" ]]; then
        echo "9999"
        return
    fi
    if [[ "$stime" == "now" ]]; then
        echo "0"
        return
    fi
    echo "$stime" | awk -F: '{ print $1*60+$2 }'
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
    # Explicit immediate run
    [[ "$stime" == "now" ]] && return 0
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

# Run a command with a portable timeout.
# Usage: run_with_timeout <seconds> <command> [args...]
# Exit codes:
#   0       — command succeeded
#   1-123, 125-255 — command's real exit status (preserved; not remapped)
#   124     — timeout (GNU timeout/gtimeout parity)
#   2       — invalid <seconds> or missing command
# Ambiguity: if the command itself exits 124, callers cannot distinguish that
# from a wrapper timeout. complete.sh treats any non-zero (including 124) as
# cleanup_failed — same operational path.
run_with_timeout() {
    local secs="${1:-}"
    shift || true

    if [[ -z "$secs" || ! "$secs" =~ ^[1-9][0-9]*$ ]]; then
        echo "run_with_timeout: invalid duration '$secs' (need positive integer)" >&2
        return 2
    fi
    if [[ $# -lt 1 ]]; then
        echo "run_with_timeout: missing command" >&2
        return 2
    fi

    if command -v gtimeout &>/dev/null; then
        gtimeout "$secs" "$@"
        return $?
    fi
    if command -v timeout &>/dev/null; then
        timeout "$secs" "$@"
        return $?
    fi

    # Pure-bash fallback (Bash 3.2 / macOS without GNU coreutils).
    # Under set -m / command substitution, killing only the watchdog subshell does
    # not interrupt its sleep child — wait would block for the full timeout.
    # Kill the watchdog process group (PGID == killer_pid) so sleep dies immediately.
    local prev_opts=$-
    local marker child_pid killer_pid exit_code=0
    marker="$(mktemp "${TMPDIR:-/tmp}/solar-rwt.XXXXXX")" || return 2
    rm -f "$marker"

    set -m
    "$@" &
    child_pid=$!
    (
        sleep "$secs"
        if kill -0 "$child_pid" 2>/dev/null; then
            printf '1' > "$marker"
            kill -- -"$child_pid" 2>/dev/null || kill "$child_pid" 2>/dev/null || true
        fi
    ) &
    killer_pid=$!

    set +e
    wait "$child_pid" 2>/dev/null
    exit_code=$?
    kill -TERM -"$killer_pid" 2>/dev/null || kill -TERM "$killer_pid" 2>/dev/null || true
    kill -KILL -"$killer_pid" 2>/dev/null || kill -KILL "$killer_pid" 2>/dev/null || true
    wait "$killer_pid" 2>/dev/null || true

    # Restore shell options touched here (monitor + errexit)
    if [[ "$prev_opts" == *m* ]]; then
        set -m
    else
        set +m
    fi
    if [[ "$prev_opts" == *e* ]]; then
        set -e
    else
        set +e
    fi

    if [[ -f "$marker" ]]; then
        rm -f "$marker"
        return 124
    fi
    rm -f "$marker"
    return "$exit_code"
}

# Get timeout command (macOS compatibility)
get_timeout_cmd() {
    if command -v gtimeout &>/dev/null; then
        echo "gtimeout"
    elif command -v timeout &>/dev/null; then
        echo "timeout"
    else
        echo ""  # No timeout available
    fi
}

# Parse CSV resources (compatible with extract_meta)
parse_resources() {
    local resources_str="$1"
    echo "$resources_str" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | awk 'NF'
}

parse_csv_meta() {
    local raw="$1"
    echo "$raw" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | awk 'NF'
}

# Extract blocked_by_task_ids from frontmatter.
# Canonical format is CSV inline:
#   blocked_by_task_ids: "id1,id2"
# Also supports YAML list format for resilience:
#   blocked_by_task_ids:
#     - "id1"
#     - "id2"
extract_blocked_by_task_ids() {
    local file="$1"
    awk '
        BEGIN { in_fm = 0; in_blocked = 0 }
        /^---[[:space:]]*$/ {
            if (in_fm == 0) {
                in_fm = 1
                next
            }
            exit
        }
        in_fm == 0 { next }
        /^blocked_by_task_ids:[[:space:]]*/ {
            value = $0
            sub(/^blocked_by_task_ids:[[:space:]]*/, "", value)
            gsub(/["'\''[:space:]]/, "", value)
            if (value != "") {
                print value
                exit
            }
            in_blocked = 1
            next
        }
        in_blocked == 1 && /^[[:space:]]*-[[:space:]]*/ {
            value = $0
            sub(/^[[:space:]]*-[[:space:]]*/, "", value)
            gsub(/["'\''[:space:]]/, "", value)
            if (value != "") {
                print value
            }
            next
        }
        in_blocked == 1 {
            exit
        }
    ' "$file" | paste -sd ',' -
}

is_task_terminal() {
    local task_id="$1"
    local task_file
    task_file="$(find_task "$task_id")"
    [[ -z "$task_file" ]] && return 0

    case "$(get_status "$task_file")" in
        completed|archived|error) return 0 ;;
        *) return 1 ;;
    esac
}

list_unresolved_dependencies() {
    local file="$1"
    local blocked_by dep
    blocked_by="$(extract_blocked_by_task_ids "$file")"
    [[ -z "$blocked_by" ]] && return 0

    for dep in $(parse_csv_meta "$blocked_by"); do
        if ! is_task_terminal "$dep"; then
            echo "$dep"
        fi
    done
}

has_unresolved_dependencies() {
    local file="$1"
    local dep
    while IFS= read -r dep; do
        [[ -n "$dep" ]] && return 0
    done < <(list_unresolved_dependencies "$file")
    return 1
}

list_open_task_ids() {
    local f id
    for f in "$DIR_DRAFTS"/*.md "$DIR_PLANNED"/*.md "$DIR_QUEUED"/*.md "$DIR_ACTIVE"/*.md "$DIR_ERROR"/*.md; do
        [[ -e "$f" ]] || continue
        id="$(extract_meta "$f" "id")"
        [[ -n "$id" ]] && echo "$id"
    done
}

# Set or update a frontmatter key=value in a task file.
# If the key exists, replaces it. If not, inserts it before the closing ---.
# Usage: set_meta <file> <key> <value>
set_meta() {
    local file="$1"
    local key="$2"
    local value="$3"
    if grep -q "^${key}:" "$file" 2>/dev/null; then
        sed -i.bak "s|^${key}:.*|${key}: ${value}|" "$file"
        rm -f "${file}.bak"
    else
        awk -v k="$key" -v v="$value" '
            /^---$/ && ++count == 2 && !done {
                print k ": " v
                done = 1
            }
            { print }
        ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
    fi
}

# Parse recurring_last_run (UTC ISO-8601) to epoch seconds.
# BSD date treats a trailing "Z" as a literal, not UTC — force TZ=UTC so
# recurring_min_interval is not skewed by the local offset (e.g. CEST +2h
# made a 7200s interval always appear elapsed).
recurring_last_run_epoch() {
    local last_run="$1"
    local last_norm ts=""

    [[ -z "$last_run" ]] && { echo 0; return; }

    if [[ "$last_run" == *[Zz] ]]; then
        ts="$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$last_run" +%s 2>/dev/null || true)"
    else
        # Offset form: 2026-07-27T12:00:00+02:00 → +0200 for BSD date
        last_norm="$(echo "$last_run" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/')"
        ts="$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "$last_norm" +%s 2>/dev/null || true)"
    fi

    if [[ -z "$ts" ]] && command -v gdate >/dev/null 2>&1; then
        ts="$(gdate -d "$last_run" +%s 2>/dev/null || true)"
    elif [[ -z "$ts" ]] && date -d "1970-01-01" +%s >/dev/null 2>&1; then
        ts="$(date -d "$last_run" +%s 2>/dev/null || true)"
    fi

    echo "${ts:-0}"
}

# Check if recurring task is ready to run (race protection)
is_recurring_ready() {
    local file="$1"
    local recurring=$(extract_meta "$file" "recurring")
    [[ "$recurring" != "true" ]] && return 0  # Not recurring, always ready

    local last_run=$(extract_meta "$file" "recurring_last_run")
    [[ -z "$last_run" ]] && return 0  # Never run, ready

    local min_interval=$(extract_meta "$file" "recurring_min_interval")
    min_interval=${min_interval:-86400}  # Default 24h

    local last_epoch now_epoch elapsed
    last_epoch="$(recurring_last_run_epoch "$last_run")"
    now_epoch=$(date +%s)
    elapsed=$((now_epoch - last_epoch))

    [[ $elapsed -ge $min_interval ]]
}

# Timezone-aware scheduling check (stub for Phase 2)
is_scheduled_now_tz() {
    local file="$1"

    # First check basic schedule (existing logic)
    is_scheduled_now "$file" || return 1

    # Check timezone if specified
    local tz=$(extract_meta "$file" "scheduled_timezone")
    if [[ -n "$tz" && "$tz" != "local" ]]; then
        # Convert scheduled time to target timezone
        # Note: Requires TZ env var manipulation
        # For now, warn if timezone specified but not implemented
        log_msg "Warning: scheduled_timezone='$tz' specified but timezone conversion not yet implemented"
    fi

    return 0
}
