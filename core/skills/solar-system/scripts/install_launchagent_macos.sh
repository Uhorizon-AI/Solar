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

tmp_plist="$(mktemp)"
bash core/skills/solar-system/scripts/render_launchagent_plist.sh "$tmp_plist" >/dev/null

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
echo "Features: ${SOLAR_SYSTEM_FEATURES:-}"
echo "Logs:"
echo "  stdout: ${SOLAR_SYSTEM_STDOUT_PATH:-/tmp/com.solar.system.out}"
echo "  stderr: ${SOLAR_SYSTEM_STDERR_PATH:-/tmp/com.solar.system.err}"
