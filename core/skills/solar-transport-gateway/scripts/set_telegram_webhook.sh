#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Missing TELEGRAM_BOT_TOKEN in .env"
  exit 1
fi

base=""
if [[ -n "${SOLAR_CLOUDFLARED_HOSTNAME:-}" && "${SOLAR_CLOUDFLARED_HOSTNAME:-}" != "REPLACE_ME" ]]; then
  base="https://${SOLAR_CLOUDFLARED_HOSTNAME}"
elif [[ -n "${SOLAR_WEBHOOK_PUBLIC_URL:-}" && "${SOLAR_WEBHOOK_PUBLIC_URL:-}" != "REPLACE_ME" ]]; then
  # Backward compatibility for older env blocks.
  base="${SOLAR_WEBHOOK_PUBLIC_URL%/}"
fi

if [[ -z "$base" ]]; then
  echo "Missing public webhook host."
  echo "Set SOLAR_CLOUDFLARED_HOSTNAME in .env (recommended)."
  exit 1
fi

base_path="${SOLAR_HTTP_WEBHOOK_BASE:-/webhook}"
path="${base_path%/}/telegram"
url="${base}${path}"

curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${url}"

echo ""
echo "OK: webhook set to ${url}"
