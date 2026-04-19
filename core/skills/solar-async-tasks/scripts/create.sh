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

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --queued)         DEST="queued"; shift ;;
        --priority)       PRIORITY="$2"; shift 2 ;;
        --scheduled-time) SCHEDULED_TIME="$2"; shift 2 ;;
        --body-file)      BODY_FILE="$2"; shift 2 ;;
        --provider)       PROVIDER="$2"; shift 2 ;;
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
  --provider P         Lock this task to a specific provider: codex | claude | gemini.
                       The worker passes it to solar-router as strict mode (no fallback).
                       Only valid with --queued.

Examples:
  # Human workflow (draft → plan → approve)
  create.sh "My Task" "Do something"

  # AI subtask: direct to queued with a body file
  create.sh --queued --priority normal --body-file /tmp/body.md "My Task"

  # AI subtask: locked to a specific provider (strict mode)
  create.sh --queued --provider claude --body-file /tmp/review.md "Claude review"

  # AI subtask: inline description, run immediately
  create.sh --queued --scheduled-time now "Quick Task" "Short one-liner prompt"
USAGE
    exit 1
fi

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
        [[ -n "$PROVIDER" ]] && echo "provider: \"$PROVIDER\""
        echo "---"
        echo ""
        echo "# $TITLE"
        echo ""
        echo "$BODY"
    } > "$FILENAME"
else
    # drafts: minimal schema (plan.sh / approve.sh add the rest)
    cat > "$FILENAME" <<EOF
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

echo "Task created: $FILENAME"
echo "ID: $ID"
