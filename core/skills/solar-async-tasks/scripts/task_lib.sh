#!/bin/bash

# Shared library for solar-async-tasks
# Sourced by other scripts

# NOTE: Worker inherits SOLAR_WORKSPACE from parent caller; skip re-discovery when set.
# CLI and sync paths always run discovery (resolve_solar_paths.sh). Intentional exception.
if [[ -z "${SOLAR_WORKSPACE:-}" ]]; then
  _TASK_RESOLVE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
  if [[ -f "$_TASK_RESOLVE_SCRIPT" ]]; then
    # shellcheck source=/dev/null
    source "$_TASK_RESOLVE_SCRIPT"
    solar_resolve_paths --quiet 2>/dev/null || true
  fi
fi

# solar-state is the only reader and writer of the task queue. These scripts
# call its CLI. SOLAR_TASK_ROOT remains only so resource hooks, which are
# configuration, can still be found under async-tasks/hooks/.
SOLAR_STATE_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-state/scripts" && pwd)/solar_state.py"

state() {
  python3 "$SOLAR_STATE_PY" "$@"
}

# Machine state lives outside the workspace. SOLAR_TASK_ROOT is the explicit
# override for hook configuration; the task queue itself is solar-state.
_TASK_RUNTIME_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-paths/scripts" && pwd)/solar_runtime_paths.sh"
# shellcheck source=/dev/null
source "$_TASK_RUNTIME_LIB"
if [[ -z "${SOLAR_TASK_ROOT:-}" ]]; then
  export SOLAR_TASK_ROOT="$(solar_runtime_dir async-tasks)"
else
  export SOLAR_TASK_ROOT
fi

# Resource hooks stay under async-tasks/hooks/ (configuration, not task state).
# Their lock files live beside them. The templates read DIR_LOCKS with set -u.
export HOOKS_DIR="$SOLAR_TASK_ROOT/hooks"
export DIR_LOCKS="$SOLAR_TASK_ROOT/.locks"

# The queue is not a directory anymore. This only creates the hook lock dir.
ensure_dirs() {
    mkdir -p "$DIR_LOCKS"
}

# Execution logs live in runtime/task-logs/, and the base stores the path.
setup_logging() {
    if [[ -z "${LOG_DIR:-}" ]]; then
        export LOG_DIR
        LOG_DIR="$(solar_runtime_dir task-logs)"
    fi
    mkdir -p "$LOG_DIR"
}

cleanup_old_logs() {
    [[ ! -d "${LOG_DIR:-}" ]] && return 0
    local removed
    removed=$(find "$LOG_DIR" -maxdepth 1 -type f -name '*.log' -mtime +7 -print -delete 2>/dev/null | wc -l | tr -d ' ')
    if [[ -n "$removed" && "$removed" -gt 0 ]]; then
        log_msg "Cleaned $removed log(s) older than 7 days"
    fi
}

# One frontmatter value, from the API. Empty when the key is absent.
task_field() {
    local task_id="$1" key="$2"
    state task field "$task_id" "$key" | python3 -c 'import json,sys
data=json.load(sys.stdin)
value=data.get("value")
print("" if value is None else value)'
}

task_status_of() {
    state task status "$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'
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

# Log a message
log_msg() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >&2
}

# Throwaway export so a resource hook can read the task. The hook does not
# receive a queue file, and nothing it writes back is the task.
task_export_tmp() {
    local task_id="$1"
    local dest
    dest="$(mktemp "${TMPDIR:-/tmp}/solar-task.XXXXXX")"
    if ! state task show "$task_id" >"$dest"; then
        rm -f "$dest"
        return 2
    fi
    printf '%s\n' "$dest"
}

task_body() {
    state task get "$1" | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin).get("body") or "")'
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
# The argument is a task id. The body comes from solar-state.
task_result_location() {
    local task_id="$1"
    local loc line in_result=0
    loc="$(task_field "$task_id" "result_url")"
    [[ -n "$loc" ]] && { printf '%s\n' "$loc"; return 0; }
    loc="$(task_field "$task_id" "result_path")"
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
    done < <(task_body "$task_id")
    printf '%s\n' "$task_id"
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
