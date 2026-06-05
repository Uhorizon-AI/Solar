#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_resolve_paths --quiet
ENV_FILE="$SOLAR_WORKSPACE/.env"
BLOCK_HEADER="# [solar-app] required environment"

_read_env_key() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  grep -E "^${key}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" || true
}

_resolve_app_host() {
  local file="$1" v
  for key in SOLAR_APP_HOST SOLAR_HOST_HOST SOLAR_INTERFACE_HOST; do
    v="$(_read_env_key "$file" "$key")"
    if [[ -n "$v" ]]; then
      printf '%s' "$v"
      return 0
    fi
  done
  printf '%s' "127.0.0.1"
}

_resolve_app_port() {
  local file="$1" v
  for key in SOLAR_APP_PORT SOLAR_HOST_PORT SOLAR_INTERFACE_PORT; do
    v="$(_read_env_key "$file" "$key")"
    if [[ -n "$v" ]]; then
      printf '%s' "$v"
      return 0
    fi
  done
  printf '%s' "9000"
}

_resolve_host_runtime_dir() {
  local file="$1" v
  v="$(_read_env_key "$file" "SOLAR_HOST_RUNTIME_DIR")"
  if [[ -n "$v" ]]; then
    printf '%s' "$v"
  else
    printf '%s' "sun/runtime/host"
  fi
}

APP_HOST="$(_resolve_app_host "$ENV_FILE")"
APP_PORT="$(_resolve_app_port "$ENV_FILE")"
HOST_RUNTIME_DIR="$(_resolve_host_runtime_dir "$ENV_FILE")"

tmp="$(mktemp)"
if [[ -f "$ENV_FILE" ]]; then
  grep -v '^# \[solar-app\]' "$ENV_FILE" \
    | grep -v '^SOLAR_APP_HOST=' \
    | grep -v '^SOLAR_APP_PORT=' \
    | grep -v '^SOLAR_HOST_RUNTIME_DIR=' \
    | grep -v '^SOLAR_HOST_HOST=' \
    | grep -v '^SOLAR_HOST_PORT=' \
    | grep -v '^SOLAR_INTERFACE_HOST=' \
    | grep -v '^SOLAR_INTERFACE_PORT=' \
    | grep -v '^SOLAR_INTERFACE_RUNTIME_DIR=' \
    >"$tmp" || true
else
  : >"$tmp"
fi

{
  cat "$tmp"
  echo "$BLOCK_HEADER"
  printf 'SOLAR_APP_HOST=%s\n' "$APP_HOST"
  printf 'SOLAR_APP_PORT=%s\n' "$APP_PORT"
  printf 'SOLAR_HOST_RUNTIME_DIR=%s\n' "$HOST_RUNTIME_DIR"
} >"$ENV_FILE"
rm -f "$tmp"
echo "OK: solar-app block written to .env"
if [[ "$(uname -s)" == "Darwin" ]]; then
  echo ""
  echo "Voice (dictation) — run once:"
  echo "  solar app voice doctor"
fi
