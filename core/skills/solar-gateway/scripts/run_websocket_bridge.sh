#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing dependency: uv"
  exit 1
fi

uv run --with websockets==12.0 python3 "${SCRIPT_DIR}/run_websocket_bridge.py"
