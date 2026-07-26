#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This status check currently supports macOS only." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=system_lib.sh
source "$SCRIPT_DIR/system_lib.sh"
solar_system_bind_workspace
SOLAR_WORKSPACE="$SOLAR_WORKSPACE"
cd "$SOLAR_WORKSPACE"
solar_system_load_env

LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
DOMAIN="gui/${UID}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
OUT_LOG="${SOLAR_SYSTEM_STDOUT_PATH:-$HOME/Library/Logs/com.solar.system/stdout.log}"
ERR_LOG="${SOLAR_SYSTEM_STDERR_PATH:-$HOME/Library/Logs/com.solar.system/stderr.log}"

print_tail_with_timestamps() {
  local log_file="$1"
  local lines="$2"
  local context="${3:-300}"

  tail -n "$context" "$log_file" 2>/dev/null | awk '
    BEGIN { ts = "" }
    {
      line = $0
      if (match(line, /^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\]/)) {
        ts = substr(line, 2, 19)
        print line
      } else if (ts != "") {
        print "[" ts "] " line
      } else {
        print "[no-ts] " line
      }
    }
  ' | tail -n "$lines"
}

echo "Solar system status:"
echo "  label: $LABEL"
echo "  plist: $PLIST"
echo "  features: ${SOLAR_SYSTEM_FEATURES:-}"

if [[ -f "$PLIST" ]]; then
  echo "  plist_present: true"
  plist_root="$(solar_system_plist_solar_root "$PLIST" || true)"
  plist_status="$(solar_system_classify_plist_root "$plist_root" "$SOLAR_ROOT")"
  echo "  plist_SOLAR_ROOT: ${plist_root:-<missing>}"
  echo "  active_SOLAR_ROOT: $SOLAR_ROOT"
  echo "  plist_root_status: $plist_status"
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
  print_tail_with_timestamps "$ERR_LOG" 10 || true
fi
