#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host_lib.sh
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
ENV_FILE="$SOLAR_WORKSPACE/.env"
BLOCK_HEADER="# [solar-host] required environment"
BLOCK_BODY=$(cat <<'EOF'
SOLAR_HOST_HOST=127.0.0.1
SOLAR_HOST_PORT=9000
SOLAR_HOST_RUNTIME_DIR=sun/runtime/host
EOF
)
tmp="$(mktemp)"
if [[ -f "$ENV_FILE" ]]; then
  grep -v '^# \[solar-host\]' "$ENV_FILE" | grep -v '^SOLAR_HOST_' >"$tmp" || true
else
  : >"$tmp"
fi
{
  cat "$tmp"
  echo "$BLOCK_HEADER"
  echo "$BLOCK_BODY"
} >"$ENV_FILE"
rm -f "$tmp"
echo "OK: solar-host block written to .env"
if [[ "$(uname -s)" == "Darwin" ]]; then
  echo ""
  echo "Voice (dictation) — run once:"
  echo "  solar voice doctor"
fi
