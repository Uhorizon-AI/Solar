#!/bin/bash

# Create a new task.
# Default: creates in drafts/ (human workflow: create → plan → approve).
# With --queued: creates directly in queued/ for AI-generated subtasks.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

ensure_dirs

# Defaults
DEST="drafts"
PRIORITY="normal"
SCHEDULED_TIME=""
BODY_FILE=""
PROVIDER=""
METADATA_JSON=""

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --queued)         DEST="queued"; shift ;;
        --priority)       PRIORITY="$2"; shift 2 ;;
        --scheduled-time) SCHEDULED_TIME="$2"; shift 2 ;;
        --body-file)      BODY_FILE="$2"; shift 2 ;;
        --provider)       PROVIDER="$2"; shift 2 ;;
        --metadata)       METADATA_JSON="$2"; shift 2 ;;
        --origin-channel|--origin-chat-id|--origin-request-id)
            echo "Unknown option: $1 (use --metadata JSON)" >&2
            exit 1
            ;;
        --) shift; break ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) break ;;
    esac
done

TITLE="$1"
DESCRIPTION="${2:-}"

if [[ -z "$TITLE" ]]; then
    cat >&2 <<'USAGE'
Usage: create.sh [OPTIONS] "Task Title" ["Description"]

Options:
  --queued             Create directly in queued/ (for AI-generated subtasks).
                       Skips draft/planned states and generates complete schema.
  --priority P         Task priority: high | normal | low  (default: normal)
  --scheduled-time T   scheduled_time value, e.g. "now" or "10:00"  (default: now when --queued)
  --body-file FILE     Read task body from FILE instead of using Description arg.
                       Use this for multi-line prompts. The file content replaces
                       the body section; title heading is added automatically.
  --provider P         Lock this task to a specific provider: codex | claude | agy | agent.
                       The worker passes it to solar-router as strict mode (no fallback).
                       Only valid with --queued.
  --metadata JSON      Origin and scope metadata (message-contract). Accepts flat keys
                       origin_channel, origin_chat_id, origin_request_id and/or
                       nested origin: {channel, chat_id, request_id}, plus the
                       declared scope of the request: object, scope, effect, and
                       delivery_expected. Written as flat frontmatter. Any other key
                       is ignored: this is a closed allowlist, not a metadata
                       passthrough. notify_when: completed is set only when origin
                       metadata is present. Children should omit this flag.

Examples:
  # Human workflow (draft → plan → approve)
  create.sh "My Task" "Do something"

  # AI subtask: direct to queued with a body file (no notify)
  create.sh --queued --priority normal --body-file /tmp/body.md "My Task"

  # AI subtask: locked to a specific provider (strict mode)
  create.sh --queued --provider claude --body-file /tmp/review.md "Claude review"

  # Parent from gateway: origin metadata + notify_when
  create.sh --queued --metadata '{"origin_channel":"telegram","origin_chat_id":"456","origin_request_id":"tg:1"}' "Parent"
USAGE
    exit 1
fi

ORIGIN_CHANNEL=""
ORIGIN_CHAT_ID=""
ORIGIN_REQUEST_ID=""
SCOPE_OBJECT=""
SCOPE_BOUNDS=""
SCOPE_EFFECT=""
DELIVERY_EXPECTED=""

if [[ -n "$METADATA_JSON" ]]; then
    META_OUT="$(python3 -c '
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    sys.exit(2)
if data is None:
    data = {}
if not isinstance(data, dict):
    sys.exit(2)
origin = data.get("origin")
if not isinstance(origin, dict):
    origin = {}

def pick(flat_key, nested_key=None):
    v = data.get(flat_key)
    if v is None and nested_key is not None:
        v = origin.get(nested_key)
    if v is None:
        return ""
    # One value per output line: the caller reads these positionally, and the
    # scope keys carry prose that may arrive wrapped.
    return " ".join(str(v).split())

print(pick("origin_channel", "channel"))
print(pick("origin_chat_id", "chat_id"))
print(pick("origin_request_id", "request_id"))
print(pick("object"))
print(pick("scope"))
print(pick("effect"))
print("true" if data.get("delivery_expected") is True else "")
' "$METADATA_JSON")" || {
        echo "Error: --metadata must be a JSON object (flat origin_* or nested origin)." >&2
        exit 1
    }
    ORIGIN_CHANNEL="$(printf '%s\n' "$META_OUT" | sed -n '1p')"
    ORIGIN_CHAT_ID="$(printf '%s\n' "$META_OUT" | sed -n '2p')"
    ORIGIN_REQUEST_ID="$(printf '%s\n' "$META_OUT" | sed -n '3p')"
    SCOPE_OBJECT="$(printf '%s\n' "$META_OUT" | sed -n '4p')"
    SCOPE_BOUNDS="$(printf '%s\n' "$META_OUT" | sed -n '5p')"
    SCOPE_EFFECT="$(printf '%s\n' "$META_OUT" | sed -n '6p')"
    DELIVERY_EXPECTED="$(printf '%s\n' "$META_OUT" | sed -n '7p')"
fi

yaml_quoted() {
    python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

ID=$(generate_id)

# Choose destination directory
case "$DEST" in
    queued)  TARGET_DIR="$DIR_QUEUED" ;;
    drafts)  TARGET_DIR="$DIR_DRAFTS" ;;
    *)       echo "Error: unknown dest '$DEST'" >&2; exit 1 ;;
esac

FILENAME="$(build_task_filename "$TARGET_DIR" "$TITLE")"

# Resolve body content
if [[ -n "$BODY_FILE" ]]; then
    if [[ ! -f "$BODY_FILE" ]]; then
        echo "Error: body file not found: $BODY_FILE" >&2
        exit 1
    fi
    BODY="$(cat "$BODY_FILE")"
else
    BODY="$DESCRIPTION"
fi

HAS_ORIGIN=0
if [[ -n "$ORIGIN_CHANNEL" || -n "$ORIGIN_CHAT_ID" || -n "$ORIGIN_REQUEST_ID" ]]; then
    HAS_ORIGIN=1
fi

# The task is written to a temporary file beside its destination and moved into
# place only once the write succeeded whole. A failed redirect leaves the script
# running (no `set -e`), and a write that emits some bytes and then fails would
# otherwise leave a truncated task that looks valid: the worker would pick it up
# and the caller would be told it was created. A provider sandbox that cannot
# write into the task root hits exactly this.
TMP_FILE="${FILENAME}.partial.$$"
cleanup_partial() {
    rm -f "$TMP_FILE"
}
trap cleanup_partial EXIT

write_failed() {
    echo "Error: task file was not written: $FILENAME" >&2
    exit 1
}

# Build frontmatter based on destination
if [[ "$DEST" == "queued" ]]; then
    # --queued: full schema required for worker compatibility
    SCHED_TIME="${SCHEDULED_TIME:-now}"
    {
        echo "---"
        echo "id: \"$ID\""
        echo "title: \"$TITLE\""
        echo "created: \"$(date -Iseconds)\""
        echo "status: queued"
        echo "priority: $PRIORITY"
        echo "scheduled_time: \"$SCHED_TIME\""
        echo "recurring: false"
        [[ -n "$PROVIDER" ]] && echo "provider: $(yaml_quoted "$PROVIDER")"
        [[ -n "$ORIGIN_CHANNEL" ]] && echo "origin_channel: $(yaml_quoted "$ORIGIN_CHANNEL")"
        [[ -n "$ORIGIN_CHAT_ID" ]] && echo "origin_chat_id: $(yaml_quoted "$ORIGIN_CHAT_ID")"
        [[ -n "$ORIGIN_REQUEST_ID" ]] && echo "origin_request_id: $(yaml_quoted "$ORIGIN_REQUEST_ID")"
        [[ -n "$SCOPE_OBJECT" ]] && echo "object: $(yaml_quoted "$SCOPE_OBJECT")"
        [[ -n "$SCOPE_BOUNDS" ]] && echo "scope: $(yaml_quoted "$SCOPE_BOUNDS")"
        [[ -n "$SCOPE_EFFECT" ]] && echo "effect: $(yaml_quoted "$SCOPE_EFFECT")"
        # Written by the same call that puts the <delivery> instruction in the
        # body: dropping the instruction must drop this flag, or every task
        # would report a missing delivery.
        [[ -n "$DELIVERY_EXPECTED" ]] && echo "delivery_expected: true"
        [[ "$HAS_ORIGIN" -eq 1 ]] && echo "notify_when: completed"
        echo "---"
        echo ""
        echo "# $TITLE"
        echo ""
        echo "$BODY"
    } > "$TMP_FILE" || write_failed
else
    # drafts: minimal schema (plan.sh / approve.sh add the rest)
    cat > "$TMP_FILE" <<EOF || write_failed
---
id: "$ID"
title: "$TITLE"
created: "$(date -Iseconds)"
status: draft
priority: $PRIORITY
---

# $TITLE

$BODY
EOF
fi

# Empty means the redirect never reached the filesystem, which some shells and
# sandboxes report without a non-zero status.
[[ -s "$TMP_FILE" ]] || write_failed
mv "$TMP_FILE" "$FILENAME" || write_failed
trap - EXIT

echo "Task created: $FILENAME"
echo "ID: $ID"
