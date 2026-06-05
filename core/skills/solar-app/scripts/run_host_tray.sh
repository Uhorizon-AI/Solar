#!/usr/bin/env bash
# Dev menu bar tray — Python deps via uv (voice-uv venv), never system pip.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "WARN: tray is macOS-only" >&2
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=voice_uv_lib.sh
source "$SCRIPT_DIR/voice_uv_lib.sh"

export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv required — brew install uv && solar app voice doctor" >&2
  exit 1
fi

PY="$(voice_uv_ensure)"
if ! "$PY" -c "import rumps" 2>/dev/null; then
  echo "Installing rumps into voice-uv venv…" >&2
  uv pip install --python "$PY" rumps
fi
if ! "$PY" -c "import Quartz" 2>/dev/null; then
  echo "Installing PyObjC Quartz into voice-uv venv…" >&2
  uv pip install --python "$PY" pyobjc-framework-Quartz
fi

exec "$PY" "$SCRIPT_DIR/host_tray.py"
