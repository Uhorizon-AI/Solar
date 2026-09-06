#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-browser] required environment"

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

browser_host="127.0.0.1"
browser_port="9222"
browser_profile_dir="/tmp/com.solar.browser-profile"
browser_log_path="/tmp/com.solar.browser.log"
mcp_leak_threshold="3"

if existing="$(read_key "SOLAR_BROWSER_DEBUG_HOST")"; then
  browser_host="$existing"
fi
if existing="$(read_key "SOLAR_BROWSER_DEBUG_PORT")"; then
  browser_port="$existing"
fi
if existing="$(read_key "SOLAR_BROWSER_PROFILE_DIR")"; then
  browser_profile_dir="$existing"
fi
if existing="$(read_key "SOLAR_BROWSER_LOG_PATH")"; then
  browser_log_path="$existing"
fi
if existing="$(read_key "SOLAR_BROWSER_MCP_LEAK_THRESHOLD")"; then
  mcp_leak_threshold="$existing"
elif existing="$(read_key "SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS")"; then
  mcp_leak_threshold="$existing"
fi

tmp="$(mktemp)"
awk '
  $0 ~ /^# \[solar-browser\] required environment$/ { next }
  $0 ~ /^SOLAR_BROWSER_DEBUG_HOST=/ { next }
  $0 ~ /^SOLAR_BROWSER_DEBUG_PORT=/ { next }
  $0 ~ /^SOLAR_BROWSER_PROFILE_DIR=/ { next }
  $0 ~ /^SOLAR_BROWSER_LOG_PATH=/ { next }
  $0 ~ /^SOLAR_BROWSER_MCP_LEAK_THRESHOLD=/ { next }
  $0 ~ /^SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS=/ { next }
  { print }
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

tmp="$(mktemp)"
awk '
  NF {
    if (pending_blank && printed_any) print ""
    print
    printed_any = 1
    pending_blank = 0
    next
  }
  {
    if (printed_any) pending_blank = 1
  }
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

# Browser is the first managed block in canonical dependency order.
insert_line="$(
  awk '
    $0 ~ /^# \[solar-(router|telegram|gateway|transport-gateway|system)\] required environment$/ {
      print NR
      exit
    }
  ' "$ROOT_ENV_FILE"
)"

tmp="$(mktemp)"
if [[ -n "$insert_line" ]]; then
  if (( insert_line > 1 )); then
    sed -n "1,$((insert_line - 1))p" "$ROOT_ENV_FILE" >"$tmp"
  else
    : >"$tmp"
  fi
  echo "$BLOCK_HEADER" >>"$tmp"
  echo "SOLAR_BROWSER_DEBUG_HOST=${browser_host}" >>"$tmp"
  echo "SOLAR_BROWSER_DEBUG_PORT=${browser_port}" >>"$tmp"
  echo "SOLAR_BROWSER_PROFILE_DIR=${browser_profile_dir}" >>"$tmp"
  echo "SOLAR_BROWSER_LOG_PATH=${browser_log_path}" >>"$tmp"
  echo "SOLAR_BROWSER_MCP_LEAK_THRESHOLD=${mcp_leak_threshold}" >>"$tmp"
  printf '\n' >>"$tmp"
  sed -n "${insert_line},\$p" "$ROOT_ENV_FILE" >>"$tmp"
else
  cat "$ROOT_ENV_FILE" >"$tmp"
  if [[ -s "$tmp" ]]; then
    printf '\n' >>"$tmp"
  fi
  echo "$BLOCK_HEADER" >>"$tmp"
  echo "SOLAR_BROWSER_DEBUG_HOST=${browser_host}" >>"$tmp"
  echo "SOLAR_BROWSER_DEBUG_PORT=${browser_port}" >>"$tmp"
  echo "SOLAR_BROWSER_PROFILE_DIR=${browser_profile_dir}" >>"$tmp"
  echo "SOLAR_BROWSER_LOG_PATH=${browser_log_path}" >>"$tmp"
  echo "SOLAR_BROWSER_MCP_LEAK_THRESHOLD=${mcp_leak_threshold}" >>"$tmp"
  printf '\n' >>"$tmp"
fi
mv "$tmp" "$ROOT_ENV_FILE"

tmp="$(mktemp)"
awk '
  NF {
    if (pending_blank && printed_any) print ""
    print
    printed_any = 1
    pending_blank = 0
    next
  }
  {
    if (printed_any) pending_blank = 1
  }
' "$ROOT_ENV_FILE" >"$tmp"
mv "$tmp" "$ROOT_ENV_FILE"

echo "OK: wrote compact solar-browser block in .env."
