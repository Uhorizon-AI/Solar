#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../solar-interface/scripts/resolve_solar_paths.sh
source "$SCRIPT_DIR/../../solar-interface/scripts/resolve_solar_paths.sh"
solar_resolve_paths --quiet
cd "$SOLAR_WORKSPACE"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

BROWSER_HOST="${SOLAR_BROWSER_DEBUG_HOST:-127.0.0.1}"
BROWSER_PORT="${SOLAR_BROWSER_DEBUG_PORT:-9222}"
BROWSER_PROFILE_DIR="${SOLAR_BROWSER_PROFILE_DIR:-/tmp/com.solar.browser-profile}"
EXPECTED_MAX_MCP_PROCS=1
MCP_LEAK_THRESHOLD="${SOLAR_BROWSER_MCP_LEAK_THRESHOLD:-${SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS:-3}}"

browser_debug_url() {
  echo "http://${BROWSER_HOST}:${BROWSER_PORT}/json/version"
}

browser_targets_url() {
  echo "http://${BROWSER_HOST}:${BROWSER_PORT}/json/list"
}

fetch_devtools_json() {
  local url="$1"
  curl --silent --show-error --fail --max-time 2 "$url"
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
daemon_healthy=false
targets_healthy=false

echo "Solar Browser status:"
echo "  debug_url: $(browser_debug_url)"
echo "  targets_url: $(browser_targets_url)"
echo "  profile_dir: $BROWSER_PROFILE_DIR"

if fetch_devtools_json "$(browser_debug_url)" >/dev/null 2>&1; then
  echo "  daemon: healthy"
  daemon_healthy=true
else
  echo "  daemon: down"
  verdict="DOWN"
fi

if [[ "$daemon_healthy" == "true" ]]; then
  targets_json=""
  if targets_json="$(fetch_devtools_json "$(browser_targets_url)" 2>/dev/null)"; then
    if printf '%s\n' "$targets_json" | grep -q '"webSocketDebuggerUrl"'; then
      page_count="$(printf '%s\n' "$targets_json" | grep -c '"type": "page"' | tr -d ' ')"
      echo "  devtools_api: healthy"
      echo "  page_targets: $page_count"
      targets_healthy=true
    else
      echo "  devtools_api: degraded (missing websocket targets)"
      verdict="PARTIAL"
    fi
  else
    echo "  devtools_api: degraded (cannot list targets)"
    verdict="PARTIAL"
  fi
fi

if mcp_count="$(count_matching_processes "chrome-devtools-mcp")"; then
  echo "  chrome_devtools_processes: $mcp_count"
  if [[ "$mcp_count" -gt "$EXPECTED_MAX_MCP_PROCS" ]]; then
    echo "  mcp_processes: degraded ($mcp_count > expected ${EXPECTED_MAX_MCP_PROCS})"
    [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
  fi

  if [[ "$mcp_count" -gt "$MCP_LEAK_THRESHOLD" ]]; then
    echo "  mcp_leak_threshold: exceeded ($mcp_count > $MCP_LEAK_THRESHOLD)"
    [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
  fi

  if [[ "$daemon_healthy" == "true" && "$targets_healthy" != "true" && "$mcp_count" -gt 0 ]]; then
    echo "  mcp_bridge: suspect (DevTools targets unavailable with MCP process(es) present)"
    [[ "$verdict" != "DOWN" ]] && verdict="PARTIAL"
  fi
else
  echo "  chrome_devtools_processes: unknown"
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
