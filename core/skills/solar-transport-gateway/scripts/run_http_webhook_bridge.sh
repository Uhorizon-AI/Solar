#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing dependency: uv"
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

uv run --with websockets==12.0 python3 scripts/run_http_webhook_bridge.py
