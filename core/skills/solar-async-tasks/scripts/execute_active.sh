#!/bin/bash

# Wrapper for execute_active.py — solar-async-tasks executor.
# Handles path setup, environment, and lifecycle (complete/error).
# All provider selection, fallback, and I/O JSON parsing is in execute_active.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

MODE="${1:---once}" # --once | --all
if [[ "$MODE" != "--once" && "$MODE" != "--all" ]]; then
    echo "Usage: $0 [--once|--all]" >&2
    exit 1
fi

ROUTER_SCRIPT="$SCRIPT_DIR/../../solar-router/scripts/run_router.py"
if [[ ! -f "$ROUTER_SCRIPT" ]]; then
    echo "Error: AI router not found: $ROUTER_SCRIPT" >&2
    exit 1
fi

# Reserved exit code of execute_active.py: "this task is waiting for children".
# Shared contract, kept in one place on each side (execute_active.py).
SUBTASK_WAITING_EXIT=20

EXECUTOR_SCRIPT="$SCRIPT_DIR/execute_active.py"
if [[ ! -f "$EXECUTOR_SCRIPT" ]]; then
    echo "Error: executor script not found: $EXECUTOR_SCRIPT" >&2
    exit 1
fi

ensure_dirs
setup_logging
cleanup_old_logs

run_one_task() {
    local task_file="$1"
    local task_id title ret child_ids child_id
    local child_id_array=()

    task_id="$(extract_meta "$task_file" "id")"
    title="$(extract_meta "$task_file" "title")"

    echo "▶ Executing task: [$task_id] $title" >&2

    # This script runs under `set -e`: a bare `python3 …; ret=$?` would abort the
    # worker on any non-zero status, before a parent that is waiting for its
    # children can be put back in the queue, stranding it in active/.
    if python3 "$EXECUTOR_SCRIPT" "$task_file" "$ROUTER_SCRIPT" "$task_id" "$title"; then
        ret=0
    else
        ret=$?
    fi

    # 20: the executor created this task's children and did not touch the queue.
    # Moving the parent is the shell's job, here as it has always been. The
    # children come from the parent's own manifest (`key=id` pairs), not from a
    # diff of the queue: the executor knows exactly what it created.
    if [[ $ret -eq $SUBTASK_WAITING_EXIT ]]; then
        child_ids="$(extract_meta "$task_file" "subtask_ids" | tr ',' '\n' | sed 's/^[^=]*=//' | awk 'NF')"
        if [[ -z "$child_ids" ]]; then
            echo "Error: [$task_id] asked to await subtasks with an empty manifest" >&2
            return 1
        fi
        while IFS= read -r child_id; do
            [[ -z "$child_id" ]] && continue
            child_id_array+=("$child_id")
        done <<< "$child_ids"
        "$SCRIPT_DIR/await_subtasks.sh" "$task_id" "${child_id_array[@]}"
        echo "⏸️  Task paused until subtasks finish: [$task_id] $title"
        return 0
    fi

    if [[ $ret -eq 0 ]]; then
        # execute_active.py succeeded: complete the task
        "$SCRIPT_DIR/complete.sh" "$task_id"
        echo "✅ Executed task: [$task_id] $title"
        echo "   Log: $LOG_DIR/$(basename "$task_file" .md).log"
        return 0
    fi

    if [[ -f "$SOLAR_TASK_ROOT/cancelled/$(basename "$task_file")" ]]; then
        echo "Cancelled task: $task_id"
        return 0
    fi
    # execute_active.py already moved the file to error/ and wrote the log.
    local error_file="$DIR_ERROR/$(basename "$task_file")"
    if [[ -f "$error_file" ]]; then
        bash "$SCRIPT_DIR/notify_if_configured.sh" "$error_file" || true
    fi
    return 1
}

ACTIVE_TASKS=()
while IFS= read -r f; do
    ACTIVE_TASKS+=("$f")
done < <(find "$DIR_ACTIVE" -name "*.md" 2>/dev/null | sort)

if [[ ${#ACTIVE_TASKS[@]} -eq 0 ]]; then
    echo "⏸️  No active tasks to execute"
    exit 0
fi

failures=0
for task_file in "${ACTIVE_TASKS[@]}"; do
    if ! run_one_task "$task_file"; then
        failures=$((failures + 1))
    fi
    [[ "$MODE" == "--once" ]] && break
done

if [[ $failures -gt 0 ]]; then
    exit 1
fi
exit 0
