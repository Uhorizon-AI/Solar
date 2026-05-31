#!/usr/bin/env bash
# Verify uv + rumps runtime for Solar Host menu bar tray (macOS).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "SKIP: tray is macOS-only"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing dependency: uv (brew install uv)" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOLAR_APP="$SCRIPT_DIR/host_platform/macos/dist/Solar.app"

uv run --with rumps python3 -c "import rumps; print('OK: rumps', rumps.__version__)"

terminal_notifier_path() {
  local p
  for p in /opt/homebrew/bin/terminal-notifier /usr/local/bin/terminal-notifier; do
    if [[ -x "$p" ]]; then
      echo "$p"
      return 0
    fi
  done
  command -v terminal-notifier 2>/dev/null || true
}

TN="$(terminal_notifier_path)"
if [[ -z "$TN" ]]; then
  echo "FAIL: terminal-notifier required for notifications (dev tray and Solar.app)" >&2
  echo "  brew install terminal-notifier" >&2
  exit 1
fi
echo "OK: terminal-notifier ($TN)"

if [[ -d "$SOLAR_APP" ]]; then
  echo "OK: Solar.app present — menu bar tray; alerts via terminal-notifier (-sender Solar)"
else
  echo "OK: dev tray — run: uv run --with rumps python3 …/host_tray.py"
  echo "     optional: bash core/skills/solar-host/scripts/build_solar_tray_app.sh"
fi
