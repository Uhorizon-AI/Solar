#!/bin/bash

# Execute active tasks using AI router with provider fallback.
# - Reads active task body as semantic instructions
# - Tries providers from SOLAR_ROUTER_PROVIDER_PRIORITY
# - On success: saves output log and completes task
# - On failure: marks task as error and moves it to error/

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

ensure_dirs
LOG_DIR="$SOLAR_TASK_ROOT/logs"
mkdir -p "$LOG_DIR"

priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-codex,claude,gemini}}"
providers="$(echo "$priority" | awk -F',' '
{
    for (i=1; i<=NF; i++) {
        p=$i
        gsub(/^[ \t]+|[ \t]+$/, "", p)
        if (p != "" && !seen[p]++) {
            out = (out == "" ? p : out "," p)
        }
    }
}
END { print out }')"

if [[ -z "$providers" ]]; then
    echo "Error: SOLAR_ROUTER_PROVIDER_PRIORITY is empty." >&2
    exit 1
fi

strip_frontmatter() {
    local file="$1"
    awk '
        NR==1 && $0=="---" { in_fm=1; next }
        in_fm && $0=="---" { in_fm=0; next }
        !in_fm { print }
    ' "$file"
}

build_prompt() {
    local task_id="$1"
    local title="$2"
    local body="$3"
    cat <<EOF
You are executing a Solar asynchronous task.
Follow the task instructions exactly as written in the task body.
If the task asks to act as an agent and use a skill, do so.

Task ID: $task_id
Task Title: $title

Task Body:
$body
EOF
}

call_router() {
    local provider="$1"
    local prompt="$2"
    local task_id="$3"

    local payload
    payload="$(python3 - <<'PY' "$provider" "$prompt" "$task_id"
import json, sys
provider = sys.argv[1]
prompt = sys.argv[2]
task_id = sys.argv[3]
print(json.dumps({
    "provider": provider,
    "text": prompt,
    "request_id": f"task_{task_id}",
    "session_id": f"task_{task_id}",
    "user_id": "solar-async-tasks"
}, ensure_ascii=True))
PY
)"
    printf "%s" "$payload" | python3 "$ROUTER_SCRIPT"
}

mark_task_error() {
    local task_file="$1"
    local task_id="$2"
    local attempted_providers="$3"
    local last_error="$4"

    sed -i.bak 's/^status:.*/status: error/' "$task_file"
    rm -f "${task_file}.bak"

    {
        echo ""
        echo "## Execution Error"
        echo "- time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "- providers_attempted: $attempted_providers"
        echo "- error: $last_error"
    } >> "$task_file"

    mv "$task_file" "$DIR_ERROR/$(basename "$task_file")"
    echo "❌ Task execution failed and moved to error/: $task_id"
}

run_one_task() {
    local task_file="$1"
    local task_id title body prompt
    local provider_attempts=""
    local last_error=""
    local success=false
    local reply=""
    local provider
    local provider_used=""
    local providers_for_task="$providers"

    task_id="$(extract_meta "$task_file" "id")"
    title="$(extract_meta "$task_file" "title")"
    # Per-task provider (e.g. provider: claude for Zoho MCP); overrides SOLAR_ROUTER_PROVIDER_PRIORITY
    local task_provider
    task_provider="$(extract_meta "$task_file" "provider")"
    task_provider="${task_provider#"${task_provider%%[![:space:]]*}"}"
    task_provider="${task_provider%"${task_provider##*[![:space:]]}"}"
    if [[ -n "$task_provider" ]]; then
        providers_for_task="$task_provider"
    fi
    [[ -z "$providers_for_task" ]] && providers_for_task="$providers"

    body="$(strip_frontmatter "$task_file")"
    prompt="$(build_prompt "$task_id" "$title" "$body")"

    IFS=',' read -r -a arr <<< "$providers_for_task"
    for provider in "${arr[@]}"; do
        provider="${provider#"${provider%%[![:space:]]*}"}"
        provider="${provider%"${provider##*[![:space:]]}"}"
        [[ -z "$provider" ]] && continue
        provider_attempts="${provider_attempts}${provider},"

        if output="$(call_router "$provider" "$prompt" "$task_id" 2>&1)"; then
            reply="$output"
            provider_used="$provider"
            success=true
            break
        else
            last_error="$output"
        fi
    done
    provider_attempts="${provider_attempts%,}"

    if [[ "$success" != "true" ]]; then
        mark_task_error "$task_file" "$task_id" "$provider_attempts" "$last_error"
        return 1
    fi

    local log_file="$LOG_DIR/${task_id}_$(date +%Y%m%d-%H%M%S)_execution.md"
    {
        echo "# Async Task Execution"
        echo ""
        echo "- task_id: $task_id"
        echo "- title: $title"
        echo "- provider_used: $provider_used"
        echo "- executed_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo ""
        echo "## Result"
        echo ""
        echo "$reply"
    } > "$log_file"

    "$SCRIPT_DIR/complete.sh" "$task_id"
    echo "✅ Executed task: [$task_id] $title"
    echo "Log: $log_file"
    return 0
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
