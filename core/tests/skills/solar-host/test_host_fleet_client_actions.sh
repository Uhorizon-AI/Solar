#!/usr/bin/env bash
# Host-2: POST /api/actions/client — allowlist, loopback, mock solar CLI.
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
export SOLAR_HOST_PORT=19006
export SOLAR_HOST_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/core/skills/solar-interface/scripts"
WS="$(cd "$WS" && pwd -P)"

cat >"$WS/core/skills/solar-interface/scripts/solar" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  "client sync") echo "MOCK_SYNC_OK"; exit 0 ;;
  "client doctor") echo "MOCK_CLIENT_DOCTOR"; exit 0 ;;
  "workspace doctor") echo "MOCK_WS_DOCTOR_FAIL"; exit 2 ;;
  *) echo "MOCK_UNKNOWN $*"; exit 99 ;;
esac
MOCK
chmod +x "$WS/core/skills/solar-interface/scripts/solar"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

python3 "$SCRIPTS/host_registry.py" add "$WS" "client-actions-smoke"

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

BASE="http://127.0.0.1:${SOLAR_HOST_PORT}"
assert_ok "host health" curl -sf "${BASE}/health" >/dev/null

SYNC_CODE="$(curl -s -o /tmp/ca_sync.json -w '%{http_code}' -X POST "${BASE}/api/actions/client" \
  -H "Content-Type: application/json" \
  -d '{"action":"sync"}')"
assert_ok "sync returns 200" test "$SYNC_CODE" = "200"
assert_ok "sync output mock" grep -q MOCK_SYNC_OK /tmp/ca_sync.json

BAD_CODE="$(curl -s -o /tmp/ca_bad.json -w '%{http_code}' -X POST "${BASE}/api/actions/client" \
  -H "Content-Type: application/json" \
  -d '{"action":"rm_rf"}')"
assert_ok "invalid action rejected" test "$BAD_CODE" = "400"

ORIGIN_CODE="$(curl -s -o /tmp/ca_origin.json -w '%{http_code}' -X POST "${BASE}/api/actions/client" \
  -H "Content-Type: application/json" \
  -H "Origin: http://evil.example" \
  -d '{"action":"sync"}')"
assert_ok "cross-origin forbidden" test "$ORIGIN_CODE" = "403"

HOST_CODE="$(curl -s -o /tmp/ca_host.json -w '%{http_code}' -X POST "${BASE}/api/actions/client" \
  -H "Content-Type: application/json" \
  -H "Host: evil.example:${SOLAR_HOST_PORT}" \
  -d '{"action":"sync"}')"
assert_ok "bad Host header forbidden" test "$HOST_CODE" = "403"

WS_DOC_CODE="$(curl -s -o /tmp/ca_wsdoc.json -w '%{http_code}' -X POST "${BASE}/api/actions/client" \
  -H "Content-Type: application/json" \
  -d '{"action":"workspace_doctor"}')"
assert_ok "workspace_doctor returns 200 envelope" test "$WS_DOC_CODE" = "200"
assert_ok "workspace_doctor exit 2" python3 -c "import json; d=json.load(open('/tmp/ca_wsdoc.json')); assert d.get('exit_code')==2"

curl -sf "${BASE}/api/events?limit=30&types=client.action.failed" >/tmp/ca_events.json
assert_ok "client.action.failed emitted" python3 <<'PY'
import json
d = json.load(open("/tmp/ca_events.json"))
types = {e["type"] for e in d.get("events", [])}
assert "client.action.failed" in types, types
PY

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
