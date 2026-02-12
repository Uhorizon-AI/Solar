#!/bin/bash

# Run the async task worker: move queued tasks to active (once or in a loop).
# Does not execute task content; only calls start_next.sh.

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
    local out
    out=$("$SCRIPT_DIR/start_next.sh" 2>&1)
    local ret=$?
    if [[ $ret -ne 0 ]]; then
        log_msg "start_next.sh failed (exit $ret): $out"
        return $ret
    fi
    # "No tasks in queue" is normal, not an error
    if [[ -n "$out" ]]; then
        echo "$out"
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
