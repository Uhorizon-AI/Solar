#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This status check currently supports macOS only." >&2
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
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
OUT_LOG="${SOLAR_SYSTEM_STDOUT_PATH:-/tmp/com.solar.system.out}"
ERR_LOG="${SOLAR_SYSTEM_STDERR_PATH:-/tmp/com.solar.system.err}"

echo "Solar system status:"
echo "  label: $LABEL"
echo "  plist: $PLIST"
echo "  features: ${SOLAR_SYSTEM_FEATURES:-}"

if [[ -f "$PLIST" ]]; then
  echo "  plist_present: true"
else
  echo "  plist_present: false"
fi

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "  launchctl_loaded: true"
else
  echo "  launchctl_loaded: false"
fi

echo "  stdout_log: $OUT_LOG"
echo "  stderr_log: $ERR_LOG"

if [[ -f "$OUT_LOG" ]]; then
  echo ""
  echo "Last 10 stdout lines:"
  tail -n 10 "$OUT_LOG" || true
fi

if [[ -f "$ERR_LOG" ]]; then
  echo ""
  echo "Last 10 stderr lines:"
  tail -n 10 "$ERR_LOG" || true
fi
