#!/usr/bin/env bash
# Verify uv + rumps runtime for Solar Host menu bar tray (macOS).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "SKIP: tray is macOS-only"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOLAR_APP="$SCRIPT_DIR/host_platform/macos/dist/Solar.app"

# shellcheck source=voice_uv_lib.sh
source "$SCRIPT_DIR/voice_uv_lib.sh"
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:$PYTHONPATH}"
if ! command -v uv >/dev/null 2>&1; then
  echo "FAIL: uv required — brew install uv && solar app voice doctor" >&2
  exit 1
fi
PY="$(voice_uv_python 2>/dev/null || voice_uv_ensure)"
"$PY" -c "import rumps; print('OK: rumps', rumps.__version__, '(voice-uv venv)')"

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
  echo "OK: dev tray — run: bash $SCRIPT_DIR/run_host_tray.sh"
  echo "     optional: bash core/skills/solar-app/scripts/build_solar_tray_app.sh"
fi
