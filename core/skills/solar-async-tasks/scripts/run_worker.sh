#!/bin/bash

# Run the async task worker (once or loop):
# 1) move queued tasks to active
# 2) execute one active task

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ONCE=false
INTERVAL=60

while [[ $# -gt 0 ]]; do
    case "$1" in
        --once) ONCE=true; shift ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        *) echo "Usage: $0 [--once] [--interval SECS]" >&2; exit 1 ;;
    esac
done

ensure_dirs

run_cycle() {
    local out_start out_exec
    out_start=$("$SCRIPT_DIR/start_next.sh" 2>&1)
    local ret_start=$?
    if [[ $ret_start -ne 0 ]]; then
        log_msg "start_next.sh failed (exit $ret_start): $out_start"
        return $ret_start
    fi

    if [[ -n "$out_start" ]]; then
        echo "$out_start"
    fi

    out_exec=$("$SCRIPT_DIR/execute_active.sh" --once 2>&1)
    local ret_exec=$?
    if [[ $ret_exec -ne 0 ]]; then
        log_msg "execute_active.sh failed (exit $ret_exec): $out_exec"
        return $ret_exec
    fi

    if [[ -n "$out_exec" ]]; then
        echo "$out_exec"
    fi
    return 0
}

if $ONCE; then
    run_cycle
    exit $?
fi

# Loop mode: clean exit on SIGINT/SIGTERM
trap 'log_msg "Worker stopping."; exit 0' SIGINT SIGTERM

while true; do
    run_cycle || true
    sleep "$INTERVAL"
done
