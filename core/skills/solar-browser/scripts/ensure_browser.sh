#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

BROWSER_HOST="${SOLAR_BROWSER_DEBUG_HOST:-127.0.0.1}"
BROWSER_PORT="${SOLAR_BROWSER_DEBUG_PORT:-9222}"
BROWSER_PROFILE_DIR="${SOLAR_BROWSER_PROFILE_DIR:-/tmp/com.solar.browser-profile}"
BROWSER_LOG_PATH="${SOLAR_BROWSER_LOG_PATH:-/tmp/com.solar.browser.log}"
START_TIMEOUT="${SOLAR_BROWSER_START_TIMEOUT_SECS:-15}"
MAX_MCP_PROCS="${SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS:-3}"

browser_debug_url() {
  echo "http://${BROWSER_HOST}:${BROWSER_PORT}/json/version"
}

browser_ready() {
  curl --silent --show-error --fail --max-time 2 "$(browser_debug_url)" >/dev/null 2>&1
}

find_browser_binary() {
  if [[ -n "${SOLAR_BROWSER_BINARY:-}" && -x "${SOLAR_BROWSER_BINARY}" ]]; then
    echo "${SOLAR_BROWSER_BINARY}"
    return 0
  fi

  local candidates=(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"
    "$HOME/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"
    "/Applications/Chromium.app/Contents/MacOS/Chromium"
    "$HOME/Applications/Chromium.app/Contents/MacOS/Chromium"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

cleanup_excess_browser_mcp_processes() {
  local keep="$MAX_MCP_PROCS"
  if ! [[ "$keep" =~ ^[0-9]+$ ]]; then
    echo "⚠️  Invalid browser MCP process cap=$keep, skipping browser MCP cleanup."
    return 0
  fi

  local tmp
  tmp="$(mktemp)"
  # macOS BSD ps uses etime= (D-HH:MM:SS) instead of etimes= (GNU, integer secs)
  ps -axo pid=,etime=,command= | awk '
    function etime_to_secs(e,    parts, days, h, m, s, n) {
      days = 0
      if (split(e, parts, "-") == 2) { days = parts[1] + 0; e = parts[2] }
      n = split(e, parts, ":")
      if (n == 3) { h = parts[1]+0; m = parts[2]+0; s = parts[3]+0 }
      else        { h = 0;          m = parts[1]+0; s = parts[2]+0 }
      return days*86400 + h*3600 + m*60 + s
    }
    index($0, "chrome-devtools-mcp") {
      pid   = $1
      secs  = etime_to_secs($2)
      if (pid ~ /^[0-9]+$/ && secs ~ /^[0-9]+$/) {
        print pid "\t" secs
      }
    }
  ' | sort -k2,2nr >"$tmp"

  local total
  total="$(wc -l <"$tmp" | tr -d ' ')"
  if [[ "$total" -le "$keep" ]]; then
    rm -f "$tmp"
    return 0
  fi

  local excess
  excess=$((total - keep))
  echo "🧹 Trimming $excess stale browser DevTools MCP process(es), keeping $keep most recent."

  local line pid
  while IFS= read -r line && [[ "$excess" -gt 0 ]]; do
    pid="$(printf '%s\n' "$line" | awk '{print $1}')"
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      kill "$pid" 2>/dev/null || true
      excess=$((excess - 1))
    fi
  done <"$tmp"

  rm -f "$tmp"
}

list_daemon_pids() {
  ps -axo pid=,command= | awk -v profile="$BROWSER_PROFILE_DIR" -v port="$BROWSER_PORT" '
    index($0, "--remote-debugging-port=" port) && index($0, "--user-data-dir=" profile) {
      pid = $1
      if (pid ~ /^[0-9]+$/) print pid
    }
  '
}

kill_stale_daemons() {
  local pid
  local found=0
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    found=1
    kill "$pid" 2>/dev/null || true
  done < <(list_daemon_pids)

  if [[ "$found" -eq 1 ]]; then
    sleep 1
  fi
}

cleanup_excess_browser_mcp_processes

if browser_ready; then
  echo "✅ Solar browser already healthy at $(browser_debug_url)"
  exit 0
fi

mkdir -p "$BROWSER_PROFILE_DIR"
mkdir -p "$(dirname "$BROWSER_LOG_PATH")"

kill_stale_daemons

BROWSER_BINARY="$(find_browser_binary || true)"
if [[ -z "$BROWSER_BINARY" ]]; then
  echo "❌ Could not find a browser binary. Set SOLAR_BROWSER_BINARY to continue." >&2
  exit 1
fi

nohup "$BROWSER_BINARY" \
  --remote-debugging-address="$BROWSER_HOST" \
  --remote-debugging-port="$BROWSER_PORT" \
  --user-data-dir="$BROWSER_PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  --disable-default-apps \
  --disable-sync \
  --new-window \
  about:blank >>"$BROWSER_LOG_PATH" 2>&1 &

for _ in $(seq 1 "$START_TIMEOUT"); do
  if browser_ready; then
    echo "✅ Solar browser ready at $(browser_debug_url)"
    exit 0
  fi
  sleep 1
done

echo "❌ Solar browser did not become ready at $(browser_debug_url)" >&2
echo "   Log: $BROWSER_LOG_PATH" >&2
exit 1
