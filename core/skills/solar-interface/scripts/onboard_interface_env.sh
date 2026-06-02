#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-interface] required environment"

if [[ ! -f "$ROOT_ENV_FILE" ]]; then
  touch "$ROOT_ENV_FILE"
fi

tmp="$(mktemp)"
awk '
  $0 ~ /^# \[solar-interface\] required environment$/ { next }
  $0 ~ /^SOLAR_INTERFACE_HOST=/ { next }
  $0 ~ /^SOLAR_INTERFACE_PORT=/ { next }
  $0 ~ /^SOLAR_INTERFACE_RUNTIME_DIR=/ { next }
  { print }
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

tmp="$(mktemp)"
cat "$ROOT_ENV_FILE" >"$tmp"
if [[ -s "$tmp" ]]; then
  printf '\n' >>"$tmp"
fi
cat >>"$tmp" <<'EOF'
# [solar-interface] required environment
SOLAR_INTERFACE_HOST=127.0.0.1
SOLAR_INTERFACE_PORT=7741
SOLAR_INTERFACE_RUNTIME_DIR=sun/runtime/app
EOF
mv "$tmp" "$ROOT_ENV_FILE"

echo "OK: wrote compact solar-interface block in .env."
