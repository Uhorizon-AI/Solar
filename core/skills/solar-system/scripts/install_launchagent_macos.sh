#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer currently supports macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=system_lib.sh
source "$SCRIPT_DIR/system_lib.sh"
solar_system_bind_workspace
SOLAR_WORKSPACE="$SOLAR_WORKSPACE"
cd "$SOLAR_WORKSPACE"

bash "$SOLAR_ROOT/core/skills/solar-system/scripts/onboard_system_env.sh" >/dev/null
solar_system_load_env

LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
DOMAIN="gui/${UID}"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/${LABEL}.plist"

RUNTIME_DIR="$(solar_system_runtime_dir "$SOLAR_WORKSPACE")"
ENTRYPOINT="$(solar_system_entrypoint "$SOLAR_WORKSPACE")"
ORCHESTRATOR="$(solar_system_orchestrator_script "$SOLAR_WORKSPACE")"

mkdir -p "$DEST_DIR" "$RUNTIME_DIR"

# Logs under $HOME to avoid EIO when launchd opens them at bootstrap (e.g. /tmp namespace issues)
export SOLAR_SYSTEM_STDOUT_PATH="${SOLAR_SYSTEM_STDOUT_PATH:-$HOME/Library/Logs/com.solar.system/stdout.log}"
export SOLAR_SYSTEM_STDERR_PATH="${SOLAR_SYSTEM_STDERR_PATH:-$HOME/Library/Logs/com.solar.system/stderr.log}"
STDOUT_LOG_DIR="${SOLAR_SYSTEM_STDOUT_PATH%/*}"
STDERR_LOG_DIR="${SOLAR_SYSTEM_STDERR_PATH%/*}"
mkdir -p "$STDOUT_LOG_DIR" "$STDERR_LOG_DIR"
touch "$SOLAR_SYSTEM_STDOUT_PATH" "$SOLAR_SYSTEM_STDERR_PATH"

# Compile C wrapper before plist install (entrypoint must exist for kickstart)
echo "🔨 Compiling Solar wrapper..."
gcc -o "$ENTRYPOINT" "$SOLAR_ROOT/core/skills/solar-system/scripts/Solar.c"

chmod +x "$ENTRYPOINT" "$ORCHESTRATOR" 2>/dev/null || true

# Remove legacy entrypoint under core/ if present
rm -f "$SOLAR_ROOT/core/skills/solar-system/scripts/Solar"

# Apply icon if available
ASSETS_DIR="$SOLAR_ROOT/core/skills/solar-system/assets"
ICNS_FILE="$ASSETS_DIR/Solar.icns"
SVG_FILE="$ASSETS_DIR/solar-icon.svg"
TARGET_FILE="$ENTRYPOINT"
SET_ICON_SCRIPT="$SOLAR_ROOT/core/skills/solar-system/scripts/set_icon.swift"
SVG2PNG_SCRIPT="$SOLAR_ROOT/core/skills/solar-system/scripts/svg2png.swift"

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

tmp_plist="$(mktemp)"
bash "$SOLAR_ROOT/core/skills/solar-system/scripts/render_launchagent_plist.sh" "$tmp_plist" >/dev/null

if [[ -f "$DEST_PLIST" ]] && ! cmp -s "$tmp_plist" "$DEST_PLIST"; then
  backup="${DEST_PLIST}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$DEST_PLIST" "$backup"
  echo "Backed up existing plist to: $backup"
fi

cp "$tmp_plist" "$DEST_PLIST"
rm -f "$tmp_plist"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$DEST_PLIST"
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

echo "✅ LaunchAgent installed: $LABEL"
echo "Plist: $DEST_PLIST"
echo "Entrypoint: $ENTRYPOINT"
echo "Features: ${SOLAR_SYSTEM_FEATURES:-}"
echo "Logs:"
echo "  stdout: $SOLAR_SYSTEM_STDOUT_PATH"
echo "  stderr: $SOLAR_SYSTEM_STDERR_PATH"
