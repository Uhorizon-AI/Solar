#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing dependency: uv"
  exit 1
fi

uv run --with websockets==12.0 python3 - <<'PY'
import importlib.util
import pathlib
import sys

if importlib.util.find_spec("websockets") is None:
    print("Missing dependency: websockets")
    print("Install with: uv run --with websockets==12.0 python3 ...")
    sys.exit(1)

script = pathlib.Path("scripts/run_websocket_bridge.py")
src = script.read_text(encoding="utf-8")
compile(src, str(script), "exec")
print("OK: uv runtime, websocket dependency, and script syntax are valid.")
PY

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "WARN: cloudflared not found (required for public Telegram webhook tunnel)."
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "WARN: TELEGRAM_BOT_TOKEN not set (required for webhook registration)."
fi
