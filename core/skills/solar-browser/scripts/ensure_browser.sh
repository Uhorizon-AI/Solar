#!/usr/bin/env bash
# Without --start: only MCP cleanup + readiness check; does NOT launch Chrome.
# With --start: launch Chrome if the debug port is not already responding.
# With --stop: terminate Chrome using this profile + debug port (see list_daemon_pids).
# Usage: ensure_browser.sh [--start|--stop] [--force]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

WANT_START=false
WANT_STOP=false
WANT_FORCE=false
for arg in "$@"; do
  case "$arg" in
    --start) WANT_START=true ;;
    --stop) WANT_STOP=true ;;
    --force) WANT_FORCE=true ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--start|--stop] [--force]" >&2
      echo "  (default)  Clean up excess MCP helpers; exit 0 if Chrome answers on the debug port, else 1 without launching." >&2
      echo "  --start    Launch Chrome (if needed) until the debug port is ready." >&2
      echo "  --stop     Stop Chrome bound to SOLAR_BROWSER_PROFILE_DIR + debug port." >&2
      echo "  --force    With --stop, force shutdown even if active chrome-devtools-mcp processes are detected." >&2
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --start, --stop, --force, or --help)" >&2
      exit 1
      ;;
  esac
done

if [[ "$WANT_START" == "true" && "$WANT_STOP" == "true" ]]; then
  echo "Use either --start or --stop, not both." >&2
  exit 1
fi

if [[ "$WANT_FORCE" == "true" && "$WANT_STOP" != "true" ]]; then
  echo "--force is only valid together with --stop." >&2
  exit 1
fi

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
MCP_LEAK_THRESHOLD="${SOLAR_BROWSER_MCP_LEAK_THRESHOLD:-${SOLAR_SYSTEM_MAX_BROWSER_MCP_PROCS:-3}}"

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
  local keep="$MCP_LEAK_THRESHOLD"
  if ! [[ "$keep" =~ ^[0-9]+$ ]]; then
    echo "⚠️  Invalid browser MCP leak threshold=$keep, skipping browser MCP cleanup."
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

count_browser_mcp_processes() {
  ps -axo command= | awk 'index($0, "chrome-devtools-mcp"){c++} END{print c+0}'
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

if [[ "$WANT_STOP" == "true" ]]; then
  mcp_count="$(count_browser_mcp_processes)"
  if [[ "$WANT_FORCE" != "true" && "${mcp_count:-0}" -gt 1 ]]; then
    other_count=$((mcp_count - 1))
    echo "❌ Refusing to stop shared browser: detected ${other_count} other active chrome-devtools-mcp process(es)." >&2
    echo "   Safe stop allows only your current MCP session. Use --force only when you are sure no other workflow needs this runtime." >&2
    exit 1
  fi
  cleanup_excess_browser_mcp_processes
  kill_stale_daemons
  if [[ "$WANT_FORCE" == "true" ]]; then
    echo "✅ Solar browser force-stopped (port ${BROWSER_PORT}, profile ${BROWSER_PROFILE_DIR})."
  else
    echo "✅ Solar browser stopped (port ${BROWSER_PORT}, profile ${BROWSER_PROFILE_DIR})."
  fi
  exit 0
fi

cleanup_excess_browser_mcp_processes

if browser_ready; then
  echo "✅ Solar browser already healthy at $(browser_debug_url)"
  exit 0
fi

if [[ "$WANT_START" != "true" ]]; then
  echo "ℹ️  Chrome is not listening at $(browser_debug_url) (nothing was started)." >&2
  echo "   Run: bash $SCRIPT_DIR/ensure_browser.sh --start" >&2
  echo "   …when you are about to use browser MCP (right before that work)." >&2
  exit 1
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
