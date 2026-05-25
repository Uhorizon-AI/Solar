#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Missing dependency: cloudflared"
  exit 1
fi

tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
if [[ "$tunnel_mode" == "named" ]]; then
  tunnel_name="${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}"
  tunnel_config="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
  if [[ ! -f "$tunnel_config" ]]; then
    echo "Missing named tunnel config: $tunnel_config"
    echo "Run: bash $(transport_gateway_script configure_named_tunnel.sh)"
    exit 1
  fi
  exec cloudflared tunnel --config "$tunnel_config" run "$tunnel_name"
fi

exec cloudflared tunnel --url "http://${SOLAR_HTTP_HOST:-127.0.0.1}:${SOLAR_HTTP_PORT:-8787}"
