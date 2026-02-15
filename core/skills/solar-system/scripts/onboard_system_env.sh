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
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

insert_line="$(
  awk -v block="$BLOCK_HEADER" '
    $0 ~ /^# \[[^]]+\] required environment$/ {
      if ($0 > block) {
        print NR
        exit
      }
    }
  ' "$ROOT_ENV_FILE"
)"

tmp="$(mktemp)"
if [[ -n "$insert_line" ]]; then
  if (( insert_line > 1 )); then
    sed -n "1,$((insert_line - 1))p" "$ROOT_ENV_FILE" >"$tmp"
  fi
  echo "$BLOCK_HEADER" >>"$tmp"
  echo "SOLAR_SYSTEM_FEATURES=${features}" >>"$tmp"
  sed -n "${insert_line},\$p" "$ROOT_ENV_FILE" >>"$tmp"
else
  cat "$ROOT_ENV_FILE" >"$tmp"
  if [[ -s "$tmp" ]]; then
    printf '\n' >>"$tmp"
  fi
  echo "$BLOCK_HEADER" >>"$tmp"
  echo "SOLAR_SYSTEM_FEATURES=${features}" >>"$tmp"
fi
mv "$tmp" "$ROOT_ENV_FILE"

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
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

echo "OK: wrote compact solar-system block in .env."
