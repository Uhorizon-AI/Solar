#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
PING_MODE="false"

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-telegram/scripts/validate_telegram_env.sh [--ping]

Options:
  --ping   Validate TELEGRAM_BOT_TOKEN against Telegram getMe API.

The chat id and the display options come from `.env`; the bot token comes from
the installation secret store, which only the process reads.
EOF
}

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--ping" ]]; then
  PING_MODE="true"
fi

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

SECRETS_LOADER="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-client/scripts" && pwd)/solar_secrets.sh"
# shellcheck source=../../solar-client/scripts/solar_secrets.sh
source "$SECRETS_LOADER"
solar_load_installation_secrets

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Missing TELEGRAM_CHAT_ID (visible configuration, .env)."
  exit 1
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Missing TELEGRAM_BOT_TOKEN in the installation secret store:"
  echo "  $(solar_secrets_file)"
  echo "It is not read from .env: the workspace is indexed by the IDE."
  exit 1
fi

echo "OK: chat id from the workspace, bot token from the process store."

if [[ "$PING_MODE" != "true" ]]; then
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Missing dependency: curl"
  exit 1
fi

api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"
resp="$(curl -fsS "$api_url")"

if [[ "$resp" == *'"ok":true'* ]]; then
  echo "OK: Telegram token is valid (getMe)."
  exit 0
fi

echo "Telegram validation failed: unexpected response from getMe."
exit 1
