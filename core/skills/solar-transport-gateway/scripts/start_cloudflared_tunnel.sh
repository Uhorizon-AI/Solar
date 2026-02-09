#!/usr/bin/env bash
set -euo pipefail

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Missing dependency: cloudflared"
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
if [[ "$tunnel_mode" == "named" ]]; then
  tunnel_name="${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}"
  tunnel_config="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
  if [[ ! -f "$tunnel_config" ]]; then
    echo "Missing named tunnel config: $tunnel_config"
    echo "Run: bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh"
    exit 1
  fi
  echo "Starting named tunnel $tunnel_name using $tunnel_config"
  cloudflared tunnel --config "$tunnel_config" run "$tunnel_name"
else
  host="${SOLAR_HTTP_HOST:-127.0.0.1}"
  port="${SOLAR_HTTP_PORT:-8787}"
  echo "Starting quick tunnel to http://${host}:${port}"
  echo "Copy the https://*.trycloudflare.com URL for temporary runtime use."
  cloudflared tunnel --url "http://${host}:${port}"
fi
