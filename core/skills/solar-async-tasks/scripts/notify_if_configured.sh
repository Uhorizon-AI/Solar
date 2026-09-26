#!/bin/bash

# If the completed task has notify_when: completed, send a Telegram notification
# to the allowlisted origin chat (or TELEGRAM_CHAT_ID). When the task carries a
# `## Delivery` section, that is the message: the one-screen delivery the
# executor wrote, ending in its own evidence line. Otherwise a brief line plus
# the result location. Long text is chunked (~1s apart).
# Usage: notify_if_configured.sh <task_id>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
[[ -z "$TASK_ID" ]] && exit 0
task_status_of "$TASK_ID" >/dev/null 2>&1 || exit 0

NOTIFY_WHEN=$(task_field "$TASK_ID" "notify_when")
[[ "$NOTIFY_WHEN" != "completed" ]] && exit 0

if [[ "$(task_field "$TASK_ID" "notify_delivered")" == "true" ]]; then
  exit 0
fi

TITLE=$(task_field "$TASK_ID" "title")
[[ -z "$TITLE" ]] && TITLE="Task"

# The task root is machine state outside the workspace: never climb out of it
# to find the workspace, its .env or the user's profile. Both come from the
# workspace itself.
WORKSPACE_DIR="${SOLAR_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../../.." && pwd)}"
SUN_DIR="$WORKSPACE_DIR/sun"
SOLAR_ROOT="${SOLAR_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
SEND_SCRIPT="$SOLAR_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh"
record_notify_failure() {
  state task set "$TASK_ID" notify_status failed >/dev/null
  state task set "$TASK_ID" notify_error "$1" >/dev/null
  state task set "$TASK_ID" notify_attempted_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
  echo "Task notification failed: $1 ($TASK_ID)" >&2
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

# The workspace `.env` carries the visible configuration (chat id, parse mode).
# The bot token is not there any more: it belongs to the process, and the
# notifier is the process. `send_telegram.sh` will not look it up on its own, so
# loading it here is what lets a completed task still reach Telegram.
# Notifications carry task titles and paths the notifier does not control. In
# Markdown a stray `_` or `*` makes Telegram reject the whole message (HTTP 400),
# so they are always sent as plain text, whatever `.env` sets.
export TELEGRAM_PARSE_MODE="none"

SECRETS_LOADER="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/solar_secrets.sh"
if [[ -f "$SECRETS_LOADER" ]]; then
  # shellcheck source=/dev/null
  source "$SECRETS_LOADER"
  solar_load_installation_secrets
fi

ORIGIN_CHAT=$(task_field "$TASK_ID" "origin_chat_id")
CHAT_ID="${ORIGIN_CHAT:-${TELEGRAM_CHAT_ID:-}}"

PROFILE="$SUN_DIR/preferences/profile.md"
[[ ! -f "$PROFILE" ]] && PROFILE="$SUN_DIR/preferences/notifications.md"
if [[ -z "$ORIGIN_CHAT" && -f "$PROFILE" ]]; then
  # Anchor the capture on the key: a bare .* is greedy and swallows every digit
  # but the last, turning a chat id of 777 into 7.
  PROFILE_CHAT=$(grep -E "telegram_chat_id:[[:space:]]*[\"']?[0-9]+" "$PROFILE" 2>/dev/null | head -n1 | sed -E "s/.*telegram_chat_id:[[:space:]]*[\"']?([0-9]+)[\"']?.*/\1/")
  [[ -n "$PROFILE_CHAT" ]] && CHAT_ID="$PROFILE_CHAT"
fi

[[ -z "$CHAT_ID" ]] && exit 0
telegram_chat_allowed "$CHAT_ID" || exit 0

export TELEGRAM_CHAT_ID="$CHAT_ID"

LOCATION="$(task_result_location "$TASK_ID")"
TASK_STATUS=$(task_status_of "$TASK_ID")
BRIEF="Task completed: ${TITLE}"
if [[ "$TASK_STATUS" == "error" ]]; then
  BRIEF="Task failed and needs attention: ${TITLE}"
  LOCATION="" # Keep execution errors and sensitive details in local logs.
fi
if [[ -n "$LOCATION" ]]; then
  BRIEF="${BRIEF}"$'\n'"${LOCATION}"
fi

# The delivery the executor wrote, copied into the task by the worker. It is the
# message: a fixed line plus a path to a file on the Mac cannot be read from a
# phone. `## Result` is deliberately not read here — it is the provider's full
# account, and sending it would be transport, not compression.
task_delivery() {
  task_body "$1" | awk '
    /^## Delivery[[:space:]]*$/ { found = 1; next }
    found && /^## / { exit }
    found { print }
  '
}

DELIVERY=""
if [[ "$TASK_STATUS" != "error" ]]; then
  DELIVERY="$(task_delivery "$TASK_ID" | sed -e '/./,$!d')"
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

DELIVERY_EXPECTED=$(task_field "$TASK_ID" "delivery_expected")
if [[ -n "$DELIVERY" ]]; then
  # The delivery already ends with its own evidence line: the title and the log
  # path would only push it off the top of the screen.
  MESSAGE="$DELIVERY"
elif [[ "$DELIVERY_EXPECTED" == "true" && "$TASK_STATUS" != "error" ]]; then
  # The work ran and the log holds it, but the one-screen delivery never came.
  # Saying so beats announcing the task as resolved.
  MESSAGE="Task finished without a delivery: ${TITLE}"
  [[ -n "$LOCATION" ]] && MESSAGE="${MESSAGE}"$'\n'"${LOCATION}"
else
  MESSAGE="$BRIEF"
fi

send_chunks "$MESSAGE" || { record_notify_failure "telegram_send_failed"; exit 1; }

state task set "$TASK_ID" notify_status delivered >/dev/null
state task set "$TASK_ID" notify_error null >/dev/null
state task set "$TASK_ID" notify_delivered true >/dev/null
