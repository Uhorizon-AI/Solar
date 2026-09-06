#!/bin/bash

# If the completed task has notify_when: completed, send a Telegram notification
# to the allowlisted origin chat (or TELEGRAM_CHAT_ID). Brief by default; optional
# notify_long: true sends the result in small ordered batches (~1s apart).
# Usage: notify_if_configured.sh <path_to_completed_task.md>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_FILE="${1:-}"
[[ -z "$TASK_FILE" || ! -f "$TASK_FILE" ]] && exit 0

NOTIFY_WHEN=$(extract_meta "$TASK_FILE" "notify_when")
[[ "$NOTIFY_WHEN" != "completed" ]] && exit 0

if [[ "$(extract_meta "$TASK_FILE" "notify_delivered")" == "true" ]]; then
  exit 0
fi

TITLE=$(extract_meta "$TASK_FILE" "title")
[[ -z "$TITLE" ]] && TITLE="Task"

SUN_DIR="$(dirname "$(dirname "$SOLAR_TASK_ROOT")")"
WORKSPACE_DIR="$(dirname "$SUN_DIR")"
SOLAR_ROOT="${SOLAR_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
SEND_SCRIPT="$SOLAR_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh"
record_notify_failure() {
  upsert_frontmatter_key "$TASK_FILE" "notify_status" "failed"
  upsert_frontmatter_key "$TASK_FILE" "notify_error" "$1"
  upsert_frontmatter_key "$TASK_FILE" "notify_attempted_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Task notification failed: $1 ($TASK_FILE)" >&2
}
if [[ ! -x "$SEND_SCRIPT" ]]; then
  record_notify_failure "sender_unavailable"
  exit 1
fi

if [[ -f "$WORKSPACE_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$WORKSPACE_DIR/.env"
  set +a
fi

ORIGIN_CHAT=$(extract_meta "$TASK_FILE" "origin_chat_id")
CHAT_ID="${ORIGIN_CHAT:-${TELEGRAM_CHAT_ID:-}}"

PROFILE="$SUN_DIR/preferences/profile.md"
[[ ! -f "$PROFILE" ]] && PROFILE="$SUN_DIR/preferences/notifications.md"
if [[ -z "$ORIGIN_CHAT" && -f "$PROFILE" ]]; then
  PROFILE_CHAT=$(grep -E "telegram_chat_id:\s*[\"']?[0-9]+" "$PROFILE" 2>/dev/null | head -n1 | sed -E "s/.*[\"']?([0-9]+)[\"']?.*/\1/")
  [[ -n "$PROFILE_CHAT" ]] && CHAT_ID="$PROFILE_CHAT"
fi

[[ -z "$CHAT_ID" ]] && exit 0
telegram_chat_allowed "$CHAT_ID" || exit 0

export TELEGRAM_CHAT_ID="$CHAT_ID"

LOCATION="$(task_result_location "$TASK_FILE")"
TASK_STATUS=$(extract_meta "$TASK_FILE" "status")
BRIEF="Tarea completada: ${TITLE}"
if [[ "$TASK_STATUS" == "error" ]]; then
  BRIEF="La tarea ha fallado y necesita atención: ${TITLE}"
  LOCATION="" # Keep execution errors and sensitive details in local logs.
fi
if [[ -n "$LOCATION" ]]; then
  BRIEF="${BRIEF}"$'\n'"${LOCATION}"
fi

send_chunks() {
  local text="$1"
  local chunk rest
  rest="$text"
  local first=1
  while [[ -n "$rest" ]]; do
    if [[ ${#rest} -le 3500 ]]; then
      chunk="$rest"
      rest=""
    else
      chunk="${rest:0:3500}"
      rest="${rest:3500}"
    fi
    if [[ "$first" -eq 0 ]]; then
      sleep 1
    fi
    first=0
    (cd "$WORKSPACE_DIR" && bash "$SEND_SCRIPT" "$chunk") || return 1
  done
  return 0
}

NOTIFY_LONG=$(extract_meta "$TASK_FILE" "notify_long")
if [[ "$NOTIFY_LONG" == "true" && "$TASK_STATUS" != "error" ]]; then
  BODY="$(awk 'found{print} /^## Result/{found=1}' "$TASK_FILE")"
  [[ -z "$BODY" ]] && BODY="$BRIEF"
  LONG_TEXT="${BRIEF}"$'\n\n'"${BODY}"
  send_chunks "$LONG_TEXT" || { record_notify_failure "telegram_send_failed"; exit 1; }
else
  (cd "$WORKSPACE_DIR" && bash "$SEND_SCRIPT" "$BRIEF") || { record_notify_failure "telegram_send_failed"; exit 1; }
fi

upsert_frontmatter_key "$TASK_FILE" "notify_status" "delivered"
upsert_frontmatter_key "$TASK_FILE" "notify_error" "null"
upsert_frontmatter_key "$TASK_FILE" "notify_delivered" "true"
