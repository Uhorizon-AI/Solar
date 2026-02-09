#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh

Requirements in .env:
  SOLAR_CLOUDFLARED_TUNNEL_NAME
  SOLAR_CLOUDFLARED_HOSTNAME
  SOLAR_CLOUDFLARED_CONFIG
  SOLAR_HTTP_HOST
  SOLAR_HTTP_PORT
EOF
  exit 0
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Missing dependency: cloudflared"
  exit 1
fi

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

name="${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}"
hostname="${SOLAR_CLOUDFLARED_HOSTNAME:-REPLACE_ME}"
config_file="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
local_host="${SOLAR_HTTP_HOST:-127.0.0.1}"
local_port="${SOLAR_HTTP_PORT:-8787}"

if [[ "$hostname" == "REPLACE_ME" || -z "$hostname" ]]; then
  echo "Set SOLAR_CLOUDFLARED_HOSTNAME in .env (for example webhook.yourdomain.com)"
  exit 1
fi

echo "Step 1: cloudflared login (browser auth)"
cloudflared tunnel login

if ! cloudflared tunnel list | awk '{print $1}' | grep -qx "$name"; then
  echo "Step 2: create tunnel $name"
  cloudflared tunnel create "$name"
else
  echo "Tunnel $name already exists."
fi

echo "Step 3: route DNS $hostname -> tunnel $name"
cloudflared tunnel route dns "$name" "$hostname"

credentials_file="$(ls -1 "$HOME/.cloudflared"/*.json 2>/dev/null | head -n1 || true)"
if [[ -z "$credentials_file" ]]; then
  echo "Could not locate credentials JSON in ~/.cloudflared"
  exit 1
fi

mkdir -p "$(dirname "$config_file")"
cat >"$config_file" <<EOF
tunnel: $name
credentials-file: $credentials_file
ingress:
  - hostname: $hostname
    service: http://${local_host}:${local_port}
  - service: http_status:404
EOF

echo "Wrote config: $config_file"
echo "Run named tunnel:"
echo "  cloudflared tunnel --config \"$config_file\" run \"$name\""
