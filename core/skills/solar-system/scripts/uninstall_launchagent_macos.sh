#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This uninstaller currently supports macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
DOMAIN="gui/${UID}"
DEST_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

if [[ -f "$DEST_PLIST" ]]; then
  rm -f "$DEST_PLIST"
  echo "Removed plist: $DEST_PLIST"
fi

echo "✅ LaunchAgent uninstalled: $LABEL"
