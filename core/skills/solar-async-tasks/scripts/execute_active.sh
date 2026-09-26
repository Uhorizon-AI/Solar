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
SUBTASK_WAITING_EXIT=20

EXECUTOR_SCRIPT="$SCRIPT_DIR/execute_active.py"
if [[ ! -f "$EXECUTOR_SCRIPT" ]]; then
    echo "Error: executor script not found: $EXECUTOR_SCRIPT" >&2
    exit 1
fi

setup_logging
cleanup_old_logs

run_one_task() {
    local task_id="$1"
    local title ret
    local child_id_array=()

    title="$(task_field "$task_id" "title")"
    echo "▶ Executing task: [$task_id] $title" >&2

    if python3 "$EXECUTOR_SCRIPT" "$task_id" "$ROUTER_SCRIPT"; then
        ret=0
    else
        ret=$?
    fi

    if [[ $ret -eq $SUBTASK_WAITING_EXIT ]]; then
        local manifest
        manifest="$(task_field "$task_id" "subtask_ids")"
        if [[ -z "$manifest" ]]; then
            echo "Error: [$task_id] asked to await subtasks with an empty manifest" >&2
            return 1
        fi
        local child_id
        while IFS= read -r child_id; do
            [[ -z "$child_id" ]] && continue
            child_id_array+=("$child_id")
        done < <(printf '%s\n' "$manifest" | tr ',' '\n' | sed 's/^[^=]*=//' | awk 'NF')
        if [[ ${#child_id_array[@]} -eq 0 ]]; then
            echo "Error: [$task_id] asked to await subtasks with an empty manifest" >&2
            return 1
        fi
        "$SCRIPT_DIR/await_subtasks.sh" "$task_id" "${child_id_array[@]}"
        echo "⏸️  Task paused until subtasks finish: [$task_id] $title"
        return 0
    fi

    if [[ $ret -eq 0 ]]; then
        "$SCRIPT_DIR/complete.sh" "$task_id"
        echo "✅ Executed task: [$task_id] $title"
        echo "   Log: $LOG_DIR/${task_id}.log"
        return 0
    fi

    local status
    status="$(task_status_of "$task_id" 2>/dev/null || true)"
    if [[ "$status" == "cancelled" ]]; then
        echo "Cancelled task: $task_id"
        return 0
    fi
    if [[ "$status" == "error" ]]; then
        bash "$SCRIPT_DIR/notify_if_configured.sh" "$task_id" || true
    fi
    return 1
}

ACTIVE_IDS=()
while IFS= read -r task_id; do
    [[ -n "$task_id" ]] && ACTIVE_IDS+=("$task_id")
done < <(state task list --status active | python3 -c 'import json,sys
for row in json.load(sys.stdin):
    print(row["id"])')

if [[ ${#ACTIVE_IDS[@]} -eq 0 ]]; then
    echo "⏸️  No active tasks to execute"
    exit 0
fi

failures=0
for task_id in "${ACTIVE_IDS[@]}"; do
    if ! run_one_task "$task_id"; then
        failures=$((failures + 1))
    fi
    [[ "$MODE" == "--once" ]] && break
done

if [[ $failures -gt 0 ]]; then
    exit 1
fi
exit 0
