#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
parse_mode_default="Markdown"
disable_preview_default="true"

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-telegram/scripts/send_telegram.sh "Message text"
  echo "Message text" | bash core/skills/solar-telegram/scripts/send_telegram.sh

Behavior:
- Loads `.env` for visible configuration only (chat id, parse mode, preview).
- Takes TELEGRAM_BOT_TOKEN from the environment. It is never read from `.env`,
  and this script does not open the installation secret store: the Solar runtime
  that calls it (gateway, task notifier, MCP send tool) puts the token in the
  environment after passing its own gate.
EOF
}

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

# Preserve caller overrides across `.env` sourcing (e.g. calendar-sync forces HTML;
# async-tasks notify forces origin chat_id).
_PRESERVE_PARSE_MODE="${TELEGRAM_PARSE_MODE-__UNSET__}"
_PRESERVE_DISABLE_PREVIEW="${TELEGRAM_DISABLE_PREVIEW-__UNSET__}"
_PRESERVE_CHAT_ID="${TELEGRAM_CHAT_ID-__UNSET__}"
# The token is an installation secret: whatever a workspace `.env` still says
# about it is ignored, including an empty value.
_PRESERVE_BOT_TOKEN="${TELEGRAM_BOT_TOKEN-__UNSET__}"

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

if [[ "$_PRESERVE_PARSE_MODE" != "__UNSET__" ]]; then
  TELEGRAM_PARSE_MODE="$_PRESERVE_PARSE_MODE"
fi
if [[ "$_PRESERVE_DISABLE_PREVIEW" != "__UNSET__" ]]; then
  TELEGRAM_DISABLE_PREVIEW="$_PRESERVE_DISABLE_PREVIEW"
fi
if [[ "$_PRESERVE_CHAT_ID" != "__UNSET__" ]]; then
  TELEGRAM_CHAT_ID="$_PRESERVE_CHAT_ID"
fi
if [[ "$_PRESERVE_BOT_TOKEN" == "__UNSET__" ]]; then
  unset TELEGRAM_BOT_TOKEN
else
  TELEGRAM_BOT_TOKEN="$_PRESERVE_BOT_TOKEN"
fi
unset _PRESERVE_PARSE_MODE _PRESERVE_DISABLE_PREVIEW _PRESERVE_CHAT_ID _PRESERVE_BOT_TOKEN

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Missing required key: TELEGRAM_BOT_TOKEN"
  echo "It is an installation secret held by the Solar process, not by the"
  echo "workspace. To send from an agent, use the gated MCP tool"
  echo "solar_telegram_send, which needs an approval Louis grants out of band."
  exit 1
fi

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Missing required key: TELEGRAM_CHAT_ID"
  echo "Define it in .env (root) or environment."
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Missing dependency: curl"
  exit 1
fi

msg="${1:-}"
if [[ -z "$msg" ]]; then
  if [ ! -t 0 ]; then
    msg="$(cat)"
  fi
fi

if [[ -z "$msg" ]]; then
  echo "Message is required."
  usage
  exit 1
fi

parse_mode="${TELEGRAM_PARSE_MODE:-$parse_mode_default}"
disable_preview="${TELEGRAM_DISABLE_PREVIEW:-$disable_preview_default}"

api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
resp="$(
  curl -fsS -X POST "$api_url" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${msg}" \
    --data-urlencode "parse_mode=${parse_mode}" \
    --data-urlencode "disable_web_page_preview=${disable_preview}"
)"

if [[ "$resp" == *'"ok":true'* ]]; then
  echo "OK: message sent to Telegram chat ${TELEGRAM_CHAT_ID}."
  exit 0
fi

echo "Telegram send failed: unexpected API response."
echo "$resp"
exit 1
