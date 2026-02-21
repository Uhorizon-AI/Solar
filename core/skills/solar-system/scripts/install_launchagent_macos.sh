#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer currently supports macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

bash core/skills/solar-system/scripts/onboard_system_env.sh >/dev/null

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
DOMAIN="gui/${UID}"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/${LABEL}.plist"

mkdir -p "$DEST_DIR"

# Logs under $HOME to avoid EIO when launchd opens them at bootstrap (e.g. /tmp namespace issues)
export SOLAR_SYSTEM_STDOUT_PATH="${SOLAR_SYSTEM_STDOUT_PATH:-$HOME/Library/Logs/com.solar.system/stdout.log}"
export SOLAR_SYSTEM_STDERR_PATH="${SOLAR_SYSTEM_STDERR_PATH:-$HOME/Library/Logs/com.solar.system/stderr.log}"
STDOUT_LOG_DIR="${SOLAR_SYSTEM_STDOUT_PATH%/*}"
STDERR_LOG_DIR="${SOLAR_SYSTEM_STDERR_PATH%/*}"
mkdir -p "$STDOUT_LOG_DIR" "$STDERR_LOG_DIR"
touch "$SOLAR_SYSTEM_STDOUT_PATH" "$SOLAR_SYSTEM_STDERR_PATH"

tmp_plist="$(mktemp)"
bash core/skills/solar-system/scripts/render_launchagent_plist.sh "$tmp_plist" >/dev/null

if [[ -f "$DEST_PLIST" ]] && ! cmp -s "$tmp_plist" "$DEST_PLIST"; then
  backup="${DEST_PLIST}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$DEST_PLIST" "$backup"
  echo "Backed up existing plist to: $backup"
fi

cp "$tmp_plist" "$DEST_PLIST"
rm -f "$tmp_plist"

# Compile C wrapper for robust icon support
echo "🔨 Compiling Solar wrapper..."
gcc -o "$REPO_ROOT/core/skills/solar-system/scripts/Solar" \
    "$REPO_ROOT/core/skills/solar-system/scripts/Solar.c"

# Ensure entrypoint scripts are executable
chmod +x "$REPO_ROOT/core/skills/solar-system/scripts/Solar" \
         "$REPO_ROOT/core/skills/solar-system/scripts/run_orchestrator.sh" 2>/dev/null || true

# Apply icon if available
ASSETS_DIR="$REPO_ROOT/core/skills/solar-system/assets"
ICNS_FILE="$ASSETS_DIR/Solar.icns"
SVG_FILE="$ASSETS_DIR/solar-icon.svg"
TARGET_FILE="$REPO_ROOT/core/skills/solar-system/scripts/Solar"
SET_ICON_SCRIPT="$REPO_ROOT/core/skills/solar-system/scripts/set_icon.swift"
SVG2PNG_SCRIPT="$REPO_ROOT/core/skills/solar-system/scripts/svg2png.swift"

# Generate ICNS from SVG if needed (using WebKit for transparency)
if [[ -f "$SVG_FILE" && -f "$SVG2PNG_SCRIPT" ]]; then
  # Only regenerate if ICNS doesn't exist or SVG is newer
  if [[ ! -f "$ICNS_FILE" ]] || [[ "$SVG_FILE" -nt "$ICNS_FILE" ]]; then
    echo "🎨 Generating transparent icon from SVG..."
    ICONSET_DIR="$ASSETS_DIR/solar.iconset"
    mkdir -p "$ICONSET_DIR"
    
    # Generate PNGs at required sizes
    for size in 16 32 128 256 512; do
      swift "$SVG2PNG_SCRIPT" "$SVG_FILE" "$ICONSET_DIR/icon_${size}x${size}.png" "$size" >/dev/null 2>&1 || true
      swift "$SVG2PNG_SCRIPT" "$SVG_FILE" "$ICONSET_DIR/icon_${size}x${size}@2x.png" "$((size*2))" >/dev/null 2>&1 || true
    done
    
    if hash iconutil 2>/dev/null; then
      iconutil -c icns "$ICONSET_DIR" -o "$ICNS_FILE"
      rm -rf "$ICONSET_DIR"
    fi
  fi
fi

if [[ -f "$ICNS_FILE" && -f "$TARGET_FILE" && -f "$SET_ICON_SCRIPT" ]]; then
  echo "🎨 Applying custom icon to binary..."
  swift "$SET_ICON_SCRIPT" "$ICNS_FILE" "$TARGET_FILE" || true
fi

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$DEST_PLIST"
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

echo "✅ LaunchAgent installed: $LABEL"
echo "Plist: $DEST_PLIST"
echo "Features: ${SOLAR_SYSTEM_FEATURES:-}"
echo "Logs:"
echo "  stdout: $SOLAR_SYSTEM_STDOUT_PATH"
echo "  stderr: $SOLAR_SYSTEM_STDERR_PATH"
