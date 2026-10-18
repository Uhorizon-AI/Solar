#!/bin/bash

# Diagnostic worker (once or loop): claim the next ready task and run it here, in the foreground.
#
# This is NOT a production entry point. Production runs the resident supervisor
# (ensure_async_tasks.sh -> launch_supervisor.sh), which dispatches by id and token and fills
# every place the applied policy allows. This script stays for diagnosis and goes through exactly
# the same reservation (capacity, provider limit, access, token) as the supervisor and
# activate.sh, so it can never exceed what they allow; it needs --diagnostic to run at all.
#
#   run_worker.sh --diagnostic [--once] [--interval SECS]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ONCE=false
INTERVAL=60
DIAGNOSTIC=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --once) ONCE=true; shift ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --diagnostic) DIAGNOSTIC=true; shift ;;
        *) echo "Usage: $0 --diagnostic [--once] [--interval SECS]" >&2; exit 1 ;;
    esac
done

if ! $DIAGNOSTIC; then
    echo "run_worker.sh is no longer a production entry point." >&2
    echo "Start async-tasks with: bash $SCRIPT_DIR/ensure_async_tasks.sh (the resident supervisor)." >&2
    echo "For diagnosis only: $0 --diagnostic [--once]" >&2
    exit 64
fi

ensure_dirs

recover_endings() {
    local endings task_id
    endings="$(state task reservations | python3 -c 'import json,sys
for row in json.load(sys.stdin):
    if row.get("phase") == "ending": print(row["task_id"])')" || return 1
    while IFS= read -r task_id; do
        [[ -n "$task_id" ]] || continue
        # A refusal leaves the reservation held. Adoption never signals processes or
        # executes an ending task; it only releases after every group is proved gone.
        state task adopt "$task_id" --worker "diagnostic-$$" >/dev/null || true
    done <<< "$endings"
}

run_cycle() {
    recover_endings || return 1
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
    recover_endings || return 1
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
