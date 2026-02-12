#!/bin/bash

# If the completed task has notify_when: completed, send a Telegram notification.
# Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env (in SOLAR_ROOT). Optional override:
# telegram_chat_id in sun/preferences/profile.md (or notifications.md). Used by complete.sh.
# Usage: notify_if_configured.sh <path_to_completed_task.md>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_FILE="${1:-}"
[[ -z "$TASK_FILE" || ! -f "$TASK_FILE" ]] && exit 0

NOTIFY_WHEN=$(extract_meta "$TASK_FILE" "notify_when")
[[ "$NOTIFY_WHEN" != "completed" ]] && exit 0

TITLE=$(extract_meta "$TASK_FILE" "title")
[[ -z "$TITLE" ]] && TITLE="Task"

# SOLAR_ROOT: parent of sun (for .env and send_telegram). SOLAR_TASK_ROOT = sun/runtime/async-tasks
SUN_DIR="$(dirname "$(dirname "$SOLAR_TASK_ROOT")")"
SOLAR_ROOT="$(dirname "$SUN_DIR")"
SEND_SCRIPT="$SOLAR_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh"
[[ ! -x "$SEND_SCRIPT" ]] && exit 0

# Prefer TELEGRAM_CHAT_ID from .env (loaded by send_telegram). Optional override from sun/preferences.
PROFILE="$SUN_DIR/preferences/profile.md"
[[ ! -f "$PROFILE" ]] && PROFILE="$SUN_DIR/preferences/notifications.md"
if [[ -f "$PROFILE" ]]; then
  CHAT_ID=$(grep -E "telegram_chat_id:\s*[\"']?[0-9]+" "$PROFILE" 2>/dev/null | head -n1 | sed -E "s/.*[\"']?([0-9]+)[\"']?.*/\1/")
  [[ -n "$CHAT_ID" ]] && export TELEGRAM_CHAT_ID="$CHAT_ID"
fi

# send_telegram loads .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) from SOLAR_ROOT
(cd "$SOLAR_ROOT" && bash "$SEND_SCRIPT" "Tarea completada: $TITLE") || true
