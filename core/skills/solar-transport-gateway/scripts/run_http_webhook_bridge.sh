#!/usr/bin/env bash
set -euo pipefail

if ! command -v poetry >/dev/null 2>&1; then
  echo "Missing dependency: poetry"
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

export POETRY_VIRTUALENVS_IN_PROJECT=true
export POETRY_CACHE_DIR="${POETRY_CACHE_DIR:-core/skills/solar-transport-gateway/.poetry-cache}"

poetry -C core/skills/solar-transport-gateway run python scripts/run_http_webhook_bridge.py
