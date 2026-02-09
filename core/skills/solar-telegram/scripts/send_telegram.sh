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
- Loads `.env` if present.
- Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
- Optionally uses TELEGRAM_PARSE_MODE and TELEGRAM_DISABLE_PREVIEW.
EOF
}

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required key: $key"
    echo "Define it in .env (root) or environment."
    exit 1
  fi
done

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
