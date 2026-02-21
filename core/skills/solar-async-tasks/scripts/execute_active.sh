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
    local task_id title

    task_id="$(extract_meta "$task_file" "id")"
    title="$(extract_meta "$task_file" "title")"

    echo "▶ Executing task: [$task_id] $title" >&2

    if python3 "$EXECUTOR_SCRIPT" "$task_file" "$ROUTER_SCRIPT" "$task_id" "$title"; then
        # execute_active.py succeeded: complete the task
        "$SCRIPT_DIR/complete.sh" "$task_id"
        echo "✅ Executed task: [$task_id] $title"
        echo "   Log: $LOG_DIR/$(basename "$task_file" .md).log"
        return 0
    else
        # execute_active.py already moved the file to error/ and wrote the log
        return 1
    fi
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
