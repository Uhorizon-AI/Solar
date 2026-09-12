#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

RUN_DIR="${SOLAR_GATEWAY_RUN_DIR:-/tmp/solar-transport-gateway}"
BRIDGE_NAME="solar-transport-gateway"

http_host="${SOLAR_HTTP_HOST:-127.0.0.1}"
http_port="${SOLAR_HTTP_PORT:-8787}"
local_health_url="http://${http_host}:${http_port}/health"

tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
public_health_url=""
if [[ "$tunnel_mode" == "named" ]]; then
  if [[ -n "${SOLAR_CLOUDFLARED_HOSTNAME:-}" && "${SOLAR_CLOUDFLARED_HOSTNAME}" != "REPLACE_ME" ]]; then
    public_health_url="https://${SOLAR_CLOUDFLARED_HOSTNAME}/health"
  fi
fi

check_pid() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

listener_pid_for_port() {
  local port="$1"
  local pid=""
  if command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
  fi
  if [[ -n "$pid" ]]; then
    echo "$pid"
    return 0
  fi
  return 1
}

check_pid_or_listener() {
  local pid_file="$1"
  local port="$2"
  if check_pid "$pid_file"; then
    return 0
  fi

  local pid=""
  pid="$(listener_pid_for_port "$port" || true)"
  if [[ -n "$pid" ]]; then
    echo "$pid" >"$pid_file"
    return 0
  fi
  return 1
}

local_ok=false
public_ok=false
connector_ok=false
ws_ok=false
http_ok=false
tunnel_ok=false

if check_pid_or_listener "$RUN_DIR/ws.pid" "${SOLAR_WS_PORT:-8765}"; then ws_ok=true; fi
if check_pid_or_listener "$RUN_DIR/http.pid" "${SOLAR_HTTP_PORT:-8787}"; then http_ok=true; fi
if check_pid "$RUN_DIR/cloudflared.pid"; then tunnel_ok=true; fi
if gateway_cloudflared_connector_ready "$RUN_DIR/cloudflared.log"; then connector_ok=true; fi

local_body="$(curl -fsS --max-time 5 "$local_health_url" 2>/dev/null || true)"
if [[ "$local_body" == *"\"bridge\": \"${BRIDGE_NAME}\""* ]]; then
  local_ok=true
fi

if [[ -n "$public_health_url" ]]; then
  public_body="$(curl -fsS --max-time 5 "$public_health_url" 2>/dev/null || true)"
  if [[ "$public_body" == *"\"bridge\": \"${BRIDGE_NAME}\""* ]]; then
    public_ok=true
  fi
fi

echo "Transport gateway status:"
echo "  http channels:     $(gateway_http_channels_label)"
echo "  telegram claim:    $(gateway_telegram_claim_label)"
echo "  ws process:        $ws_ok"
echo "  http process:      $http_ok"
echo "  tunnel process:    $tunnel_ok"
echo "  tunnel connector:  $connector_ok"
echo "  local /health:     $local_ok ($local_health_url)"
if [[ -n "$public_health_url" ]]; then
  if [[ "$public_ok" == true ]]; then
    echo "  public /health:    true ($public_health_url)"
  elif [[ "$connector_ok" == true ]]; then
    echo "  public /health:    unreachable from this host ($public_health_url)"
  else
    echo "  public /health:    false ($public_health_url)"
  fi
else
  echo "  public /health:    skipped (named hostname not configured)"
fi

if [[ "$ws_ok" != true || "$http_ok" != true || "$local_ok" != true ]]; then
  echo ""
  echo "DOWN: local transport is not healthy."
  echo "Run: bash $(transport_gateway_script setup_transport_gateway.sh)"
  exit 1
fi

# Named-tunnel public curl from the origin host hairpins and is not authoritative.
# PARTIAL only when the connector itself is not ready.
if [[ -n "$public_health_url" && "$public_ok" != true && "$connector_ok" != true ]]; then
  echo ""
  echo "PARTIAL: local transport is healthy but the tunnel connector is not ready."
  echo "Run: bash $(transport_gateway_script start_cloudflared_tunnel.sh)"
  exit 2
fi

echo ""
echo "OK: transport gateway is healthy."
