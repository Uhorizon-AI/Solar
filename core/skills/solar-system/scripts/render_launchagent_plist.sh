#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TEMPLATE="$SCRIPT_DIR/../assets/com.solar.system.plist.template"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Template not found: $TEMPLATE" >&2
  exit 1
fi

OUT_FILE="${1:-/tmp/com.solar.system.plist}"
LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
START_INTERVAL="${SOLAR_SYSTEM_LAUNCHD_START_INTERVAL:-60}"
STDOUT_PATH="${SOLAR_SYSTEM_STDOUT_PATH:-$HOME/Library/Logs/com.solar.system/stdout.log}"
STDERR_PATH="${SOLAR_SYSTEM_STDERR_PATH:-$HOME/Library/Logs/com.solar.system/stderr.log}"
ENTRYPOINT_PATH="$REPO_ROOT/core/skills/solar-system/scripts/Solar"
WORKING_DIRECTORY="$REPO_ROOT"

escape_sed() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

label_esc="$(escape_sed "$LABEL")"
interval_esc="$(escape_sed "$START_INTERVAL")"
entrypoint_esc="$(escape_sed "$ENTRYPOINT_PATH")"
working_dir_esc="$(escape_sed "$WORKING_DIRECTORY")"
stdout_esc="$(escape_sed "$STDOUT_PATH")"
stderr_esc="$(escape_sed "$STDERR_PATH")"

sed \
  -e "s/__LABEL__/$label_esc/g" \
  -e "s/__START_INTERVAL__/$interval_esc/g" \
  -e "s/__ENTRYPOINT_PATH__/$entrypoint_esc/g" \
  -e "s/__WORKING_DIRECTORY__/$working_dir_esc/g" \
  -e "s/__STDOUT_PATH__/$stdout_esc/g" \
  -e "s/__STDERR_PATH__/$stderr_esc/g" \
  "$TEMPLATE" >"$OUT_FILE"

echo "$OUT_FILE"
