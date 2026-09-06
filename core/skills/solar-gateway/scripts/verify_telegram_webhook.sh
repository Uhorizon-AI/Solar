#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Missing TELEGRAM_BOT_TOKEN in .env"
  exit 1
fi

base=""
if [[ -n "${SOLAR_CLOUDFLARED_HOSTNAME:-}" && "${SOLAR_CLOUDFLARED_HOSTNAME:-}" != "REPLACE_ME" ]]; then
  base="https://${SOLAR_CLOUDFLARED_HOSTNAME}"
fi

if [[ -z "$base" ]]; then
  echo "Missing public webhook host."
  echo "Set SOLAR_CLOUDFLARED_HOSTNAME in .env."
  exit 1
fi

base_path="${SOLAR_HTTP_WEBHOOK_BASE:-/webhook}"
path="${base_path%/}/telegram"
expected_url="${base}${path}"

info_json="$(curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo")"
actual_url="$(
  printf '%s' "$info_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
print((data.get("result") or {}).get("url") or "")
'
)"

echo "$info_json"
echo ""

if [[ -z "$actual_url" ]]; then
  echo "❌ Telegram webhook URL is empty; expected ${expected_url}" >&2
  exit 1
fi

if [[ "$actual_url" != "$expected_url" ]]; then
  echo "❌ Telegram webhook URL mismatch." >&2
  echo "   expected: ${expected_url}" >&2
  echo "   actual:   ${actual_url}" >&2
  exit 1
fi

echo "OK: webhook verified at ${actual_url}"
