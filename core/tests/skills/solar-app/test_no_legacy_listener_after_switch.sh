#!/usr/bin/env bash
# MVP-b.1 b2: workspace switch stops legacy :7741-era listeners on inactive workspace port.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    FAIL=$((FAIL + 1))
  fi
}

if ! command -v lsof >/dev/null 2>&1; then
  echo "SKIP: lsof not available"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'kill $HOST_PID $IFACE_PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

export SOLAR_APP_DATA="$TMP/appdata"
export SOLAR_HOST_OFFLINE=1
export SOLAR_APP_PORT=19006
export SOLAR_APP_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS_A="$TMP/ws-a"
WS_B="$TMP/ws-b"
mkdir -p "$WS_A/sun/runtime/app/state" "$WS_B/sun/runtime/app/state"
WS_A="$(cd "$WS_A" && pwd -P)"
WS_B="$(cd "$WS_B" && pwd -P)"

LEGACY_A="$(python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import host_registry as reg; print(reg.legacy_daemon_port('$WS_A'))")"
LEGACY_B="$(python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import host_registry as reg; print(reg.legacy_daemon_port('$WS_B'))")"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi

python3 "$SCRIPTS/host_registry.py" add "$WS_A" "a"
python3 "$SCRIPTS/host_registry.py" add "$WS_B" "b"
python3 "$SCRIPTS/host_registry.py" use "$WS_A"

# Fake legacy daemon (removed skill) — name must match cleanup heuristics.
cat >"$TMP/interface_server.py" <<PY
import http.server
import socketserver
import sys
port = int(sys.argv[1])
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler) as httpd:
    httpd.serve_forever()
PY

echo "$$" >"$WS_A/sun/runtime/app/state/interface.pid"
python3 "$TMP/interface_server.py" "$LEGACY_A" &
IFACE_PID=$!
sleep 1
echo "$IFACE_PID" >"$WS_A/sun/runtime/app/state/interface.pid"

assert_ok "legacy listener on ws_a port" lsof -i "tcp:${LEGACY_A}" -sTCP:LISTEN >/dev/null

export SOLAR_WORKSPACE="$WS_A"
python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/health" >/dev/null

START_CODE="$(curl -s -o /tmp/iface_start -w '%{http_code}' -X POST \
  "http://127.0.0.1:${SOLAR_APP_PORT}/api/runtime/interface/start")"
assert_ok "interface/start deprecated 200" test "$START_CODE" = "200"

SWITCH_CODE="$(curl -s -o /tmp/switch_body -w '%{http_code}' -X POST \
  "http://127.0.0.1:${SOLAR_APP_PORT}/api/workspaces/active" \
  -H 'Content-Type: application/json' \
  -d "{\"path\":\"$WS_B\"}")"
assert_ok "switch to ws_b" test "$SWITCH_CODE" = "200"

sleep 1

assert_ok "legacy port A not listening after switch" bash -c "! lsof -i tcp:${LEGACY_A} -sTCP:LISTEN >/dev/null 2>&1"

if kill -0 "$IFACE_PID" 2>/dev/null; then
  echo "FAIL: legacy listener still alive after switch" >&2
  FAIL=$((FAIL + 1))
else
  echo "PASS: legacy listener stopped by switch"
  PASS=$((PASS + 1))
fi
IFACE_PID=""

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
