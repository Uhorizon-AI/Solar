#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-telegram] required environment"

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-telegram/scripts/onboard_telegram_env.sh

What it does:
- Creates .env if missing.
- Writes a single compact Telegram block (no blank lines inside block).
- Preserves existing Telegram values when already defined.
EOF
}

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$ROOT_ENV_FILE" ]]; then
  touch "$ROOT_ENV_FILE"
  echo "Created $ROOT_ENV_FILE"
fi

read_key() {
  local key="$1"
  if grep -Eq "^${key}=" "$ROOT_ENV_FILE"; then
    grep -E "^${key}=" "$ROOT_ENV_FILE" | tail -n1 | cut -d= -f2-
    return 0
  fi
  return 1
}

token="REPLACE_ME"
chat_id="REPLACE_ME"
parse_mode="Markdown"
disable_preview="true"

if existing="$(read_key "TELEGRAM_BOT_TOKEN")"; then
  token="$existing"
fi
if existing="$(read_key "TELEGRAM_CHAT_ID")"; then
  chat_id="$existing"
fi
if existing="$(read_key "TELEGRAM_PARSE_MODE")"; then
  parse_mode="$existing"
fi
if existing="$(read_key "TELEGRAM_DISABLE_PREVIEW")"; then
  disable_preview="$existing"
fi

tmp="$(mktemp)"
awk '
  $0 ~ /^TELEGRAM_BOT_TOKEN=/ { next }
  $0 ~ /^TELEGRAM_CHAT_ID=/ { next }
  $0 ~ /^TELEGRAM_PARSE_MODE=/ { next }
  $0 ~ /^TELEGRAM_DISABLE_PREVIEW=/ { next }
  $0 ~ /^# \[solar-telegram\] required environment$/ { next }
  { print }
' "$ROOT_ENV_FILE" >"$tmp"

mv "$tmp" "$ROOT_ENV_FILE"

{
  if [[ -s "$ROOT_ENV_FILE" ]]; then
    printf '\n'
  fi
  echo "$BLOCK_HEADER"
  echo "TELEGRAM_BOT_TOKEN=${token}"
  echo "TELEGRAM_CHAT_ID=${chat_id}"
  echo "TELEGRAM_PARSE_MODE=${parse_mode}"
  echo "TELEGRAM_DISABLE_PREVIEW=${disable_preview}"
} >>"$ROOT_ENV_FILE"

echo ""
echo "OK: wrote compact Telegram block in .env."
echo "Next step: set real TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID if still REPLACE_ME."
