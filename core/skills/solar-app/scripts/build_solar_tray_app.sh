#!/usr/bin/env bash
# Build Solar.app (menu bar). Notifications appear as "Solar" in System Settings, not Python.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/host_platform/macos/app"
DIST="$SCRIPT_DIR/host_platform/macos/dist"

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing: uv (brew install uv)" >&2
  exit 1
fi

# Remove stale bundles so py2app does not recurse dist/ into the package tree.
rm -rf "$APP_DIR/build" "$APP_DIR/dist" "$DIST"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/scripts/host_platform/macos"
rsync -a \
  --exclude dist \
  --exclude build \
  --exclude __pycache__ \
  --exclude '*.pyc' \
  "$SCRIPT_DIR/host_platform/" "$STAGE/scripts/host_platform/"
# Tray imports voice_core + registry (not under host_platform/).
for mod in voice_core.py voice_config.py voice_mic.py host_registry.py host_workspace_context.py; do
  cp "$SCRIPT_DIR/$mod" "$STAGE/scripts/$mod"
done
cp "$APP_DIR/setup.py" "$APP_DIR/tray_entry.py" "$STAGE/"

(
  cd "$STAGE"
  uv run --with py2app --with rumps --with pyobjc-framework-Quartz python setup.py py2app
)

if [[ ! -d "$STAGE/dist/Solar.app" ]]; then
  echo "ERROR: Solar.app not produced under $STAGE/dist" >&2
  exit 1
fi

mkdir -p "$DIST"
cp -R "$STAGE/dist/Solar.app" "$DIST/"

# py2app bundles Homebrew Python.framework (org.python.python). macOS then lists
# "Python" in Settings → Notifications even when alerts use Solar.app. Re-label the
# embedded framework so usernoted does not treat it as a separate notification app.
if command -v /usr/libexec/PlistBuddy >/dev/null 2>&1; then
  patched=0
  while IFS= read -r -d '' PY_FW_PLIST; do
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier ai.uhorizon.solar.host.python-runtime" "$PY_FW_PLIST" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string ai.uhorizon.solar.host.python-runtime" "$PY_FW_PLIST"
    /usr/libexec/PlistBuddy -c "Set :CFBundleName Solar Runtime" "$PY_FW_PLIST" 2>/dev/null \
      || true
    patched=$((patched + 1))
  done < <(find "$DIST/Solar.app/Contents/Frameworks/Python.framework" -path '*/Resources/Info.plist' -print0 2>/dev/null || true)
  if [[ "$patched" -gt 0 ]]; then
    echo "Patched $patched embedded Python.framework Info.plist (notifications → Solar only)."
  fi
fi

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$DIST/Solar.app" >/dev/null
fi

echo "OK: $DIST/Solar.app"
echo "Run: open \"$DIST/Solar.app\""
