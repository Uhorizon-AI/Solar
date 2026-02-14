#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-system] required environment"

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

features="async-tasks"
if existing="$(read_key "SOLAR_SYSTEM_FEATURES")"; then
  features="$existing"
fi

tmp="$(mktemp)"
awk '
  $0 ~ /^# \[solar-system\] required environment$/ { next }
  $0 ~ /^SOLAR_SYSTEM_FEATURES=/ { next }
  { print }
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

{
  if [[ -s "$ROOT_ENV_FILE" ]]; then printf '\n'; fi
  echo "$BLOCK_HEADER"
  echo "SOLAR_SYSTEM_FEATURES=${features}"
} >>"$ROOT_ENV_FILE"

echo "OK: wrote compact solar-system block in .env."
