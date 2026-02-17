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
