#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-transport-gateway] required environment"

if [[ ! -f "$ROOT_ENV_FILE" ]]; then
  touch "$ROOT_ENV_FILE"
  echo "Created $ROOT_ENV_FILE"
fi

WORK_ENV_FILE="$(mktemp)"
cp "$ROOT_ENV_FILE" "$WORK_ENV_FILE"
cleanup() {
  rm -f "$WORK_ENV_FILE" "${tmp:-}"
}
trap cleanup EXIT

read_key() {
  local key="$1"
  if grep -Eq "^${key}=" "$WORK_ENV_FILE"; then
    grep -E "^${key}=" "$WORK_ENV_FILE" | tail -n1 | cut -d= -f2-
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
  # Legacy cleanup: remove deprecated transport flag if present.
  $0 ~ /^SOLAR_ENABLE_DIRECT_TELEGRAM_REPLY=/ { next }
  $0 ~ /^# \[solar-transport-gateway\] required environment$/ { next }
  { print }
' "$WORK_ENV_FILE" >"$tmp"
mv "$tmp" "$WORK_ENV_FILE"

# Normalize spacing: keep at most one blank line between blocks and remove
# leading/trailing blank lines to keep repeated runs idempotent.
tmp="$(mktemp)"
awk '
  NF {
    if (pending_blank && printed_any) {
      print ""
    }
    print
    printed_any = 1
    pending_blank = 0
    next
  }
  {
    if (printed_any) {
      pending_blank = 1
    }
  }
' "$WORK_ENV_FILE" >"$tmp"
mv "$tmp" "$WORK_ENV_FILE"

insert_line="$(
  awk -v block="$BLOCK_HEADER" '
    $0 ~ /^# \[[^]]+\] required environment$/ {
      if ($0 > block) {
        print NR
        exit
      }
    }
  ' "$WORK_ENV_FILE"
)"

tmp="$(mktemp)"
if [[ -n "$insert_line" ]]; then
  if (( insert_line > 1 )); then
    sed -n "1,$((insert_line - 1))p" "$WORK_ENV_FILE" >"$tmp"
  fi
  echo "$BLOCK_HEADER" >>"$tmp"
  echo "SOLAR_WS_HOST=${ws_host}" >>"$tmp"
  echo "SOLAR_WS_PORT=${ws_port}" >>"$tmp"
  echo "SOLAR_WS_PATH=${ws_path}" >>"$tmp"
  echo "SOLAR_HTTP_HOST=${http_host}" >>"$tmp"
  echo "SOLAR_HTTP_PORT=${http_port}" >>"$tmp"
  echo "SOLAR_HTTP_WEBHOOK_BASE=${http_webhook_base}" >>"$tmp"
  echo "SOLAR_TUNNEL_MODE=${tunnel_mode}" >>"$tmp"
  echo "SOLAR_CLOUDFLARED_TUNNEL_NAME=${tunnel_name}" >>"$tmp"
  echo "SOLAR_CLOUDFLARED_HOSTNAME=${tunnel_hostname}" >>"$tmp"
  echo "SOLAR_CLOUDFLARED_CONFIG=${tunnel_config}" >>"$tmp"
  sed -n "${insert_line},\$p" "$WORK_ENV_FILE" >>"$tmp"
else
  cat "$WORK_ENV_FILE" >"$tmp"
  if [[ -s "$tmp" ]]; then
    printf '\n' >>"$tmp"
  fi
  echo "$BLOCK_HEADER" >>"$tmp"
  echo "SOLAR_WS_HOST=${ws_host}" >>"$tmp"
  echo "SOLAR_WS_PORT=${ws_port}" >>"$tmp"
  echo "SOLAR_WS_PATH=${ws_path}" >>"$tmp"
  echo "SOLAR_HTTP_HOST=${http_host}" >>"$tmp"
  echo "SOLAR_HTTP_PORT=${http_port}" >>"$tmp"
  echo "SOLAR_HTTP_WEBHOOK_BASE=${http_webhook_base}" >>"$tmp"
  echo "SOLAR_TUNNEL_MODE=${tunnel_mode}" >>"$tmp"
  echo "SOLAR_CLOUDFLARED_TUNNEL_NAME=${tunnel_name}" >>"$tmp"
  echo "SOLAR_CLOUDFLARED_HOSTNAME=${tunnel_hostname}" >>"$tmp"
  echo "SOLAR_CLOUDFLARED_CONFIG=${tunnel_config}" >>"$tmp"
fi
mv "$tmp" "$WORK_ENV_FILE"

# Final normalize pass after insertion to enforce stable spacing.
tmp="$(mktemp)"
awk '
  NF {
    if (pending_blank && printed_any) {
      print ""
    }
    print
    printed_any = 1
    pending_blank = 0
    next
  }
  {
    if (printed_any) {
      pending_blank = 1
    }
  }
' "$WORK_ENV_FILE" >"$tmp"
mv "$tmp" "$WORK_ENV_FILE"

if cmp -s "$WORK_ENV_FILE" "$ROOT_ENV_FILE"; then
  echo "OK: solar-transport-gateway block already up to date in .env."
else
  mv "$WORK_ENV_FILE" "$ROOT_ENV_FILE"
  WORK_ENV_FILE=""
  echo "OK: wrote compact solar-transport-gateway block in .env."
fi
