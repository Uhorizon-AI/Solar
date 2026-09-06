#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

flag="$(gateway_telegram_claim)"
if ! gateway_telegram_claim_valid; then
  echo "Invalid SOLAR_GATEWAY_CLAIM_TELEGRAM=${SOLAR_GATEWAY_CLAIM_TELEGRAM:-} (expected true|false or absent)." >&2
  exit 1
fi

if [[ "$flag" != "true" ]]; then
  if [[ "$flag" == "false" ]]; then
    echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=false: omitting setWebhook."
  else
    echo "SOLAR_GATEWAY_CLAIM_TELEGRAM unset: omitting setWebhook."
  fi
  exit 0
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Missing TELEGRAM_BOT_TOKEN in .env"
  exit 1
fi

expected=""
expected="$(gateway_telegram_expected_url)" || {
  echo "Missing public webhook host."
  echo "Set SOLAR_CLOUDFLARED_HOSTNAME in .env."
  exit 1
}

if ! live="$(gateway_telegram_live_url)"; then
  echo "Cannot verify Telegram webhook ownership; refusing setWebhook." >&2
  exit 1
fi

if [[ -n "$live" && "$live" != "$expected" ]]; then
  echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=true but webhook is not Solar's URL." >&2
  echo "   solar:   $expected" >&2
  echo "Do not set SOLAR_GATEWAY_CLAIM_TELEGRAM=true; refusing setWebhook." >&2
  exit 1
fi

curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${expected}"

echo ""
echo "OK: webhook set to ${expected}"
