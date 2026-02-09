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

missing=()
for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
  if [[ -z "${!key:-}" ]]; then
    missing+=("$key")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  printf 'Missing required .env keys: %s\n' "${missing[*]}"
  exit 1
fi

echo "OK: required Telegram keys are present in environment."

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
