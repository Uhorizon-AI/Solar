#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
  set +a
fi

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
url="${base}${path}"

curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${url}"

echo ""
echo "OK: webhook set to ${url}"
