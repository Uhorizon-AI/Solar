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
    local out_start out_exec claim_file claimed_id claimed_token
    claim_file="$(mktemp "${TMPDIR:-/tmp}/solar-claim.XXXXXX")"
    : >"$claim_file"
    out_start=$(SOLAR_CLAIM_FILE="$claim_file" "$SCRIPT_DIR/start_next.sh" 2>&1)
    local ret_start=$?
    if [[ $ret_start -ne 0 ]]; then
        rm -f "$claim_file"
        log_msg "start_next.sh failed (exit $ret_start): $out_start"
        return $ret_start
    fi

    if [[ -n "$out_start" ]]; then
        echo "$out_start"
    fi

    # The executor takes exactly the task that was claimed, with its token. Without a claim
    # (nothing started now) it looks for an active task nobody runs: a manual activation, or
    # one whose owner is gone; execute_active.sh decides that through the reservation.
    claimed_id=""
    claimed_token=""
    if [[ -s "$claim_file" ]]; then
        claimed_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["task_id"])' "$claim_file")"
        claimed_token="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$claim_file")"
    fi
    rm -f "$claim_file"
    if [[ -n "$claimed_id" ]]; then
        out_exec=$("$SCRIPT_DIR/execute_active.sh" --task "$claimed_id" --token "$claimed_token" 2>&1)
    else
        out_exec=$("$SCRIPT_DIR/execute_active.sh" --once 2>&1)
    fi
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
