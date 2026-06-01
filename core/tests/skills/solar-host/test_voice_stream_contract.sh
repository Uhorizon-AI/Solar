#!/usr/bin/env bash
# Voice SSE contract — mock stream only (no LLM/router).
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
export SOLAR_HOST_PORT=19008
export SOLAR_HOST_HOST=127.0.0.1
export SOLAR_HOST_BASE_URL="http://127.0.0.1:${SOLAR_HOST_PORT}"
export SOLAR_VOICE_MOCK_STREAM=1
export SOLAR_VOICE_MOCK_STREAM_FIXTURE="$SCRIPT_DIR/fixtures/voice_mock_stream.sse"
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun"
WS="$(cd "$WS" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

python3 "$SCRIPTS/host_registry.py" add "$WS" "voice-stream"

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_HOST_PORT}/health" >/dev/null

THREAD_ID="$(curl -sf -X POST "http://127.0.0.1:${SOLAR_HOST_PORT}/threads" \
  -H 'Content-Type: application/json' \
  -d '{"title":"voice mock"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['thread']['thread_id'])")"
assert_ok "create thread" test -n "$THREAD_ID"

HEADERS="$TMP/stream.headers"
BODY="$TMP/stream.body"
HTTP_CODE="$(
  curl -sS -N --max-time 15 \
    -D "$HEADERS" \
    -o "$BODY" \
    -w '%{http_code}' \
    -X POST \
    -H 'Content-Type: application/json' \
    -H 'Accept: text/event-stream' \
    -d '{"text":"mock ask","mode":"ask","provider":"auto"}' \
    "http://127.0.0.1:${SOLAR_HOST_PORT}/threads/${THREAD_ID}/stream" \
)"

assert_ok "stream HTTP 200" test "$HTTP_CODE" = "200"
assert_ok "stream content-type" grep -qi 'content-type:.*text/event-stream' "$HEADERS"
assert_ok "stream has data event" grep -q '^data:' "$BODY"

export SOLAR_VOICE_TTS=off
export SOLAR_VOICE_TEXT="mock contract question"
assert_ok "voice_cli ask mock" bash -c "python3 '$SCRIPTS/voice_cli.py' ask | grep -q 'Mock'"

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
