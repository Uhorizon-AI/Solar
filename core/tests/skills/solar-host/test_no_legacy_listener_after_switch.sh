#!/usr/bin/env bash
# MVP-b.1 b2: workspace switch stops legacy interface_server on inactive workspace port.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-host/scripts"
IFACE_SCRIPTS="$CORE_ROOT/skills/solar-interface/scripts"
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
export SOLAR_HOST_PORT=19003
export SOLAR_HOST_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS_A="$TMP/ws-a"
WS_B="$TMP/ws-b"
mkdir -p "$WS_A/sun" "$WS_B/sun"
echo "SOLAR_INTERFACE_PORT=8811" >"$WS_A/.env"
echo "SOLAR_INTERFACE_PORT=8812" >"$WS_B/.env"
WS_A="$(cd "$WS_A" && pwd -P)"
WS_B="$(cd "$WS_B" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi

python3 "$SCRIPTS/host_registry.py" add "$WS_A" "a"
python3 "$SCRIPTS/host_registry.py" add "$WS_B" "b"
python3 "$SCRIPTS/host_registry.py" use "$WS_A"

export SOLAR_WORKSPACE="$WS_A"
export SOLAR_INTERFACE_PORT=8811
export SOLAR_INTERFACE_HOST=127.0.0.1

python3 "$IFACE_SCRIPTS/interface_server.py" &
IFACE_PID=$!
sleep 2

assert_ok "legacy interface listening on 8811" lsof -i "tcp:8811" -sTCP:LISTEN >/dev/null

export SOLAR_WORKSPACE="$WS_A"
python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_HOST_PORT}/health" >/dev/null

START_CODE="$(curl -s -o /tmp/iface_start -w '%{http_code}' -X POST \
  "http://127.0.0.1:${SOLAR_HOST_PORT}/api/runtime/interface/start")"
assert_ok "interface/start deprecated 200" test "$START_CODE" = "200"

SWITCH_CODE="$(curl -s -o /tmp/switch_body -w '%{http_code}' -X POST \
  "http://127.0.0.1:${SOLAR_HOST_PORT}/api/workspaces/active" \
  -H 'Content-Type: application/json' \
  -d "{\"path\":\"$WS_B\"}")"
assert_ok "switch to ws_b" test "$SWITCH_CODE" = "200"

sleep 1

# Host unmount must stop legacy daemon — do NOT kill IFACE_PID manually here.
assert_ok "port 8811 not listening after switch" bash -c "! lsof -i tcp:8811 -sTCP:LISTEN >/dev/null 2>&1"
assert_ok "port 8812 not listening" bash -c "! lsof -i tcp:8812 -sTCP:LISTEN >/dev/null 2>&1"

if kill -0 "$IFACE_PID" 2>/dev/null; then
  echo "FAIL: legacy interface process still alive after switch" >&2
  FAIL=$((FAIL + 1))
else
  echo "PASS: legacy interface process stopped by switch"
  PASS=$((PASS + 1))
fi
IFACE_PID=""

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
