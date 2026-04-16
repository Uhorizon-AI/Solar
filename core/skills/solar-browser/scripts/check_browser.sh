#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

BROWSER_HOST="${SOLAR_BROWSER_DEBUG_HOST:-127.0.0.1}"
BROWSER_PORT="${SOLAR_BROWSER_DEBUG_PORT:-9222}"
BROWSER_PROFILE_DIR="${SOLAR_BROWSER_PROFILE_DIR:-/tmp/com.solar.browser-profile}"
MAX_MCP_PROCS="${SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS:-3}"

browser_debug_url() {
  echo "http://${BROWSER_HOST}:${BROWSER_PORT}/json/version"
}

count_matching_processes() {
  local pattern="$1"
  local output
  set +e
  output="$(pgrep -f -- "$pattern" 2>&1)"
  local code=$?
  set -e

  case "$code" in
    0)
      printf '%s\n' "$output" | wc -l | tr -d ' '
      return 0
      ;;
    1)
      echo "0"
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

verdict="HEALTHY"

echo "Solar Browser status:"
echo "  debug_url: $(browser_debug_url)"
echo "  profile_dir: $BROWSER_PROFILE_DIR"

if curl --silent --show-error --fail --max-time 2 "$(browser_debug_url)" >/dev/null 2>&1; then
  echo "  daemon: healthy"
else
  echo "  daemon: down"
  verdict="DOWN"
fi

if mcp_count="$(count_matching_processes "chrome-devtools-mcp")"; then
  if [[ "$mcp_count" -gt "$MAX_MCP_PROCS" ]]; then
    echo "  mcp_processes: leak-suspected ($mcp_count > $MAX_MCP_PROCS)"
    [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
  else
    echo "  mcp_processes: $mcp_count"
  fi
else
  echo "  mcp_processes: unknown"
  [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
fi

if daemon_count="$(count_matching_processes "--remote-debugging-port=${BROWSER_PORT}.*--user-data-dir=${BROWSER_PROFILE_DIR}")"; then
  if [[ "$daemon_count" -gt 1 ]]; then
    echo "  daemon_processes: multiple ($daemon_count)"
    [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
  else
    echo "  daemon_processes: $daemon_count"
  fi
else
  echo "  daemon_processes: unknown"
  [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
fi

echo "  verdict: $verdict"

case "$verdict" in
  HEALTHY) exit 0 ;;
  PARTIAL) exit 2 ;;
  *) exit 1 ;;
esac
