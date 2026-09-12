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
- Writes a single compact Telegram block with the *visible* configuration only.
- Preserves existing Telegram values when already defined.
- Removes TELEGRAM_BOT_TOKEN from .env: the token is an installation secret and
  lives in the process store, outside every tree the IDE indexes.
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

chat_id="REPLACE_ME"
parse_mode="Markdown"
disable_preview="true"

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
  $0 ~ /^# TELEGRAM_BOT_TOKEN is deliberately absent/ { next }
  $0 ~ /^TELEGRAM_CHAT_ID=/ { next }
  $0 ~ /^TELEGRAM_PARSE_MODE=/ { next }
  $0 ~ /^TELEGRAM_DISABLE_PREVIEW=/ { next }
  $0 ~ /^# \[solar-telegram\] required environment$/ { next }
  { print }
' "$ROOT_ENV_FILE" >"$tmp"

insert_line="$(awk '
  $0 ~ /^# \[solar-(gateway|transport-gateway|system)\] required environment$/ {
    print NR
    exit
  }
' "$tmp")"

block_file="$(mktemp)"
{
  echo "$BLOCK_HEADER"
  echo "# TELEGRAM_BOT_TOKEN is deliberately absent: installation secret, process store."
  echo "TELEGRAM_CHAT_ID=${chat_id}"
  echo "TELEGRAM_PARSE_MODE=${parse_mode}"
  echo "TELEGRAM_DISABLE_PREVIEW=${disable_preview}"
} >"$block_file"

if [[ -n "$insert_line" ]]; then
  : >"$ROOT_ENV_FILE"
  if (( insert_line > 1 )); then
    sed -n "1,$((insert_line - 1))p" "$tmp" >>"$ROOT_ENV_FILE"
    printf '\n' >>"$ROOT_ENV_FILE"
  fi
  cat "$block_file" >>"$ROOT_ENV_FILE"
  printf '\n' >>"$ROOT_ENV_FILE"
  sed -n "${insert_line},\$p" "$tmp" >>"$ROOT_ENV_FILE"
else
  mv "$tmp" "$ROOT_ENV_FILE"
  if [[ -s "$ROOT_ENV_FILE" ]]; then
    printf '\n' >>"$ROOT_ENV_FILE"
  fi
  cat "$block_file" >>"$ROOT_ENV_FILE"
fi
rm -f "$block_file"

SECRETS_LOADER="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-client/scripts" && pwd)/solar_secrets.sh"
# shellcheck source=../../solar-client/scripts/solar_secrets.sh
source "$SECRETS_LOADER"
solar_secrets_ensure >/dev/null

echo ""
echo "OK: wrote compact Telegram block in .env (no token in it)."
echo "Next step: set a real TELEGRAM_CHAT_ID if still REPLACE_ME, and put"
echo "TELEGRAM_BOT_TOKEN in the process store (0600, never in the workspace):"
echo "  $(solar_secrets_file)"
