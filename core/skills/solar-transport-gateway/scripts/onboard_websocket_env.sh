#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-transport-gateway] required environment"

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

ws_host="127.0.0.1"
ws_port="8765"
ws_path="/ws"
http_host="127.0.0.1"
http_port="8787"
http_webhook_base="/webhook"
tunnel_mode="quick"
tunnel_name="solar-gateway"
tunnel_hostname="REPLACE_ME"
tunnel_config="${HOME}/.cloudflared/solar-gateway.yml"
ai_provider_priority="codex,claude,gemini"

if existing="$(read_key "SOLAR_WS_HOST")"; then ws_host="$existing"; fi
if existing="$(read_key "SOLAR_WS_PORT")"; then ws_port="$existing"; fi
if existing="$(read_key "SOLAR_WS_PATH")"; then ws_path="$existing"; fi
if existing="$(read_key "SOLAR_HTTP_HOST")"; then http_host="$existing"; fi
if existing="$(read_key "SOLAR_HTTP_PORT")"; then http_port="$existing"; fi
if existing="$(read_key "SOLAR_HTTP_WEBHOOK_BASE")"; then
  http_webhook_base="$existing"
elif existing="$(read_key "SOLAR_HTTP_WEBHOOK_PATH")"; then
  # Backward compatibility for previous single-path config.
  if [[ "$existing" == "/webhook/"* ]]; then
    http_webhook_base="/webhook"
  fi
fi
if existing="$(read_key "SOLAR_TUNNEL_MODE")"; then tunnel_mode="$existing"; fi
if existing="$(read_key "SOLAR_CLOUDFLARED_TUNNEL_NAME")"; then tunnel_name="$existing"; fi
if existing="$(read_key "SOLAR_CLOUDFLARED_HOSTNAME")"; then tunnel_hostname="$existing"; fi
if existing="$(read_key "SOLAR_CLOUDFLARED_CONFIG")"; then tunnel_config="$existing"; fi
if existing="$(read_key "SOLAR_AI_PROVIDER_PRIORITY")"; then
  ai_provider_priority="$existing"
else
  old_default="$(read_key "SOLAR_AI_DEFAULT_PROVIDER" || true)"
  old_fallback="$(read_key "SOLAR_AI_FALLBACK_ORDER" || true)"
  old_combined="${old_default},${old_fallback}"
  old_normalized="$(
    echo "$old_combined" | awk -F',' '
      {
        for (i = 1; i <= NF; i++) {
          x = $i
          gsub(/^[ \t]+|[ \t]+$/, "", x)
          if (x == "") continue
          if (!(x in seen)) {
            seen[x] = 1
            if (out == "") out = x
            else out = out "," x
          }
        }
      }
      END { print out }
    '
  )"
  if [[ -n "$old_normalized" ]]; then
    ai_provider_priority="$old_normalized"
  fi
fi
tmp="$(mktemp)"
awk '
  $0 ~ /^SOLAR_WS_HOST=/ { next }
  $0 ~ /^SOLAR_WS_PORT=/ { next }
  $0 ~ /^SOLAR_WS_PATH=/ { next }
  $0 ~ /^SOLAR_HTTP_HOST=/ { next }
  $0 ~ /^SOLAR_HTTP_PORT=/ { next }
  $0 ~ /^SOLAR_HTTP_WEBHOOK_PATH=/ { next }
  $0 ~ /^SOLAR_HTTP_WEBHOOK_BASE=/ { next }
  $0 ~ /^SOLAR_TUNNEL_MODE=/ { next }
  $0 ~ /^SOLAR_CLOUDFLARED_TUNNEL_NAME=/ { next }
  $0 ~ /^SOLAR_CLOUDFLARED_HOSTNAME=/ { next }
  $0 ~ /^SOLAR_CLOUDFLARED_CONFIG=/ { next }
  $0 ~ /^SOLAR_WEBHOOK_PUBLIC_URL=/ { next }
  $0 ~ /^SOLAR_AI_DEFAULT_PROVIDER=/ { next }
  $0 ~ /^SOLAR_AI_FALLBACK_ORDER=/ { next }
  $0 ~ /^SOLAR_AI_ALLOWED_PROVIDERS=/ { next }
  $0 ~ /^SOLAR_AI_PROVIDER_MODE=/ { next }
  $0 ~ /^SOLAR_AI_PROVIDER_PRIORITY=/ { next }
  # Legacy cleanup: remove deprecated transport flag if present.
  $0 ~ /^SOLAR_ENABLE_DIRECT_TELEGRAM_REPLY=/ { next }
  $0 ~ /^# \[solar-transport-gateway\] required environment$/ { next }
  { print }
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

{
  if [[ -s "$ROOT_ENV_FILE" ]]; then printf '\n'; fi
  echo "$BLOCK_HEADER"
  echo "SOLAR_WS_HOST=${ws_host}"
  echo "SOLAR_WS_PORT=${ws_port}"
  echo "SOLAR_WS_PATH=${ws_path}"
  echo "SOLAR_HTTP_HOST=${http_host}"
  echo "SOLAR_HTTP_PORT=${http_port}"
  echo "SOLAR_HTTP_WEBHOOK_BASE=${http_webhook_base}"
  echo "SOLAR_TUNNEL_MODE=${tunnel_mode}"
  echo "SOLAR_CLOUDFLARED_TUNNEL_NAME=${tunnel_name}"
  echo "SOLAR_CLOUDFLARED_HOSTNAME=${tunnel_hostname}"
  echo "SOLAR_CLOUDFLARED_CONFIG=${tunnel_config}"
  echo "SOLAR_AI_PROVIDER_PRIORITY=${ai_provider_priority}"
} >>"$ROOT_ENV_FILE"

echo "OK: wrote compact solar-transport-gateway block in .env."
