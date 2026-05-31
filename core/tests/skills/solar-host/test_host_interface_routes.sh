#!/usr/bin/env bash
# MVP-b.1: Host exposes full interface API in-process on :9000.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-host/scripts"
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

TMP="$(mktemp -d)"
trap 'kill $HOST_PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

export SOLAR_APP_DATA="$TMP/appdata"
export SOLAR_HOST_OFFLINE=1
export SOLAR_HOST_PORT=19002
export SOLAR_HOST_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun"
WS="$(cd "$WS" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

python3 "$SCRIPTS/host_registry.py" add "$WS" "iface-routes"

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_HOST_PORT}/health" >/dev/null

READY="$(curl -sf "http://127.0.0.1:${SOLAR_HOST_PORT}/ready")"
assert_ok "GET /ready" bash -c "echo '$READY' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'checks' in d\""

THREAD_RESP="$(curl -sf -X POST "http://127.0.0.1:${SOLAR_HOST_PORT}/threads" \
  -H 'Content-Type: application/json' \
  -d '{"title":"route test"}')"
THREAD_ID="$(echo "$THREAD_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['thread']['thread_id'])")"
assert_ok "POST /threads" test -n "$THREAD_ID"

GET_THREAD="$(curl -sf "http://127.0.0.1:${SOLAR_HOST_PORT}/threads/${THREAD_ID}")"
assert_ok "GET /threads/{id}" bash -c "echo '$GET_THREAD' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['thread']['thread_id']=='$THREAD_ID'\""

RUN_CODE="$(curl -s -o /tmp/run_body -w '%{http_code}' -X POST \
  "http://127.0.0.1:${SOLAR_HOST_PORT}/threads/${THREAD_ID}/runs" \
  -H 'Content-Type: application/json' \
  -d '{"text":"ping","mode":"ask","provider":"auto"}')"
assert_ok "POST /threads/{id}/runs" test "$RUN_CODE" -ge 200

RUN_ID="$(python3 -c "import json; print(json.load(open('/tmp/run_body')).get('run',{}).get('run_id',''))")"
if [[ -n "$RUN_ID" ]]; then
  GET_RUN="$(curl -sf "http://127.0.0.1:${SOLAR_HOST_PORT}/runs/${RUN_ID}")"
  assert_ok "GET /runs/{id}" bash -c "echo '$GET_RUN' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['run']['run_id']=='$RUN_ID'\""
else
  echo "FAIL: POST /threads/{id}/runs missing run_id" >&2
  FAIL=$((FAIL + 1))
fi

DEL_CODE="$(curl -s -o /tmp/del_body -w '%{http_code}' -X DELETE \
  "http://127.0.0.1:${SOLAR_HOST_PORT}/threads/${THREAD_ID}")"
assert_ok "DELETE /threads/{id}" test "$DEL_CODE" = "200"

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
