#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
NON_INTERACTIVE="false"
DO_PING="false"
TEST_MESSAGE=""
TOKEN_VALUE=""
CHAT_ID_VALUE=""

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-telegram/scripts/setup_telegram.sh [options]

Options:
  --non-interactive      Do not prompt for missing values.
  --ping                 Validate token with Telegram getMe API.
  --test-message "TEXT"  Send test Telegram message after validation.
  --token "VALUE"        Set TELEGRAM_BOT_TOKEN.
  --chat-id "VALUE"      Set TELEGRAM_CHAT_ID.
  -h, --help             Show this help.

Examples:
  bash core/skills/solar-telegram/scripts/setup_telegram.sh
  bash core/skills/solar-telegram/scripts/setup_telegram.sh --ping
  bash core/skills/solar-telegram/scripts/setup_telegram.sh --ping --test-message "Solar Telegram OK"
  bash core/skills/solar-telegram/scripts/setup_telegram.sh --token "123:ABC" --chat-id "999"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive)
      NON_INTERACTIVE="true"
      shift
      ;;
    --ping)
      DO_PING="true"
      shift
      ;;
    --test-message)
      TEST_MESSAGE="${2:-}"
      if [[ -z "$TEST_MESSAGE" ]]; then
        echo "Error: --test-message requires a value."
        exit 1
      fi
      shift 2
      ;;
    --token)
      TOKEN_VALUE="${2:-}"
      if [[ -z "$TOKEN_VALUE" ]]; then
        echo "Error: --token requires a value."
        exit 1
      fi
      shift 2
      ;;
    --chat-id)
      CHAT_ID_VALUE="${2:-}"
      if [[ -z "$CHAT_ID_VALUE" ]]; then
        echo "Error: --chat-id requires a value."
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

bash core/skills/solar-telegram/scripts/onboard_telegram_env.sh

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

upsert_key() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"

  if grep -Eq "^${key}=" "$ROOT_ENV_FILE"; then
    awk -v key="$key" -v value="$value" '
      BEGIN { done=0 }
      {
        if ($0 ~ ("^" key "=") && done==0) {
          print key "=" value
          done=1
        } else {
          print $0
        }
      }
      END {
        if (done==0) print key "=" value
      }
    ' "$ROOT_ENV_FILE" >"$tmp"
  else
    cat "$ROOT_ENV_FILE" >"$tmp"
    printf "\n%s=%s\n" "$key" "$value" >>"$tmp"
  fi

  mv "$tmp" "$ROOT_ENV_FILE"
}

if [[ -n "$TOKEN_VALUE" ]]; then
  upsert_key "TELEGRAM_BOT_TOKEN" "$TOKEN_VALUE"
  echo "Updated TELEGRAM_BOT_TOKEN from provided flag."
fi

if [[ -n "$CHAT_ID_VALUE" ]]; then
  upsert_key "TELEGRAM_CHAT_ID" "$CHAT_ID_VALUE"
  echo "Updated TELEGRAM_CHAT_ID from provided flag."
fi

needs_input="false"
for key in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
  val="${!key:-}"
  if [[ -z "$val" || "$val" == "REPLACE_ME" ]]; then
    needs_input="true"
  fi
done

if [[ "$needs_input" == "true" ]]; then
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    echo "Missing required Telegram values in .env."
    echo "Pass --token and --chat-id, or set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
    exit 1
  fi

  if [[ ! -t 0 ]]; then
    echo "Interactive setup requires a TTY."
    echo "Use --non-interactive or run command from an interactive shell."
    exit 1
  fi

  echo ""
  echo "Telegram setup requires 2 values:"
  read -r -p "TELEGRAM_BOT_TOKEN: " token
  read -r -p "TELEGRAM_CHAT_ID: " chat_id

  if [[ -z "$token" || -z "$chat_id" ]]; then
    echo "Both values are required."
    exit 1
  fi

  upsert_key "TELEGRAM_BOT_TOKEN" "$token"
  upsert_key "TELEGRAM_CHAT_ID" "$chat_id"
  echo "Updated .env with Telegram credentials."
fi

if [[ "$DO_PING" == "true" ]]; then
  bash core/skills/solar-telegram/scripts/validate_telegram_env.sh --ping
else
  bash core/skills/solar-telegram/scripts/validate_telegram_env.sh
fi

if [[ -n "$TEST_MESSAGE" ]]; then
  bash core/skills/solar-telegram/scripts/send_telegram.sh "$TEST_MESSAGE"
fi

echo ""
echo "Telegram setup completed."
