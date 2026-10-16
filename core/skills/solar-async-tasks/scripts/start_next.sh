#!/bin/bash

# Claim the next ready task. Eligibility (priority, dependencies, schedule,
# recurring interval, a pending cancellation) is decided inside solar-state.
# Resource hooks run after the claim; a hook that blocks releases the task.
# The claim also takes the task's reservation (capacity, provider limit, access). The
# execution token it returns goes to the caller in the file named by SOLAR_CLAIM_FILE, as
# JSON {"task_id", "token"}, so the executor can be bound to this exact task and claim.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

WORKER="start-next-$$"
EXCLUDE=""

while true; do
    claimed_json="$(state task claim-next --worker "$WORKER" --exclude "$EXCLUDE")"
    TASK_ID="$(printf '%s' "$claimed_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id") or "")')"
    TITLE="$(printf '%s' "$claimed_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("title") or "")')"
    TOKEN="$(printf '%s' "$claimed_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token") or "")')"
    if [[ -z "$TASK_ID" ]]; then
        echo "⏸️  No tasks ready to start"
        waiting="$(printf '%s' "$claimed_json" | python3 -c 'import json,sys
rows = json.load(sys.stdin).get("waiting") or []
print(", ".join("%s (%s)" % (r.get("id") or "-", r.get("reason")) for r in rows[:5]))')"
        [[ -n "$waiting" ]] && echo "   Waiting: $waiting"
        exit 0
    fi

    export_file="$(task_export_tmp "$TASK_ID")"
    hook_failed=false
    if [[ "$(task_field "$TASK_ID" "cleanup_required")" == "true" ]]; then
        resources="$(task_field "$TASK_ID" "resources")"
        for resource in $(parse_resources "$resources"); do
            hook="$HOOKS_DIR/${resource}/pre_start.sh"
            if [[ -x "$hook" ]]; then
                echo "Running pre-start hook for: $resource"
                if ! "$hook" "$export_file"; then
                    echo "⏸️  Pre-start hook blocked task (resource busy): $TASK_ID"
                    hook_failed=true
                    break
                fi
            fi
        done
    fi
    rm -f "$export_file"

    if [[ "$hook_failed" == "true" ]]; then
        state task release "$TASK_ID" --worker "$WORKER" --token "$TOKEN" >/dev/null
        EXCLUDE="${EXCLUDE:+$EXCLUDE,}$TASK_ID"
        continue
    fi

    # Unlike activate.sh (hooks run before its claim, which stamps the interval itself),
    # the hooks here run after the claim and may release it: the interval is stamped only
    # once they have passed, so a blocked task does not consume it.
    if [[ "$(task_field "$TASK_ID" "recurring")" == "true" ]]; then
        state task set "$TASK_ID" recurring_last_run "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
    fi
    state task unset "$TASK_ID" blocked_by_task_ids >/dev/null

    if [[ -n "${SOLAR_CLAIM_FILE:-}" ]]; then
        printf '%s' "$claimed_json" | python3 -c 'import json,sys
data = json.load(sys.stdin)
json.dump({"task_id": data["id"], "token": data["token"]}, open(sys.argv[1], "w"))' "$SOLAR_CLAIM_FILE"
    fi
    echo "✅ Started task: [$TASK_ID] $TITLE"
    exit 0
done
