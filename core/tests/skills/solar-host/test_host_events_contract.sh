#!/usr/bin/env bash
# Host-Inbox: event contract — emit via API, workspace in payload, GET /api/events?types= filter.
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

TMP="$(mktemp -d)"
trap 'kill $HOST_PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

export SOLAR_APP_DATA="$TMP/appdata"
export SOLAR_HOST_OFFLINE=1
export SOLAR_HOST_PORT=19005
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

python3 "$SCRIPTS/host_registry.py" add "$WS" "events-smoke"

STORE_EXIT=0
python3 - <<'PY' "$IFACE_SCRIPTS" "$WS" || STORE_EXIT=$?
import sys
from pathlib import Path

iface = Path(sys.argv[1])
ws = sys.argv[2]
sys.path.insert(0, str(iface))

from interface_store import InterfaceStore

store = InterfaceStore(ws)
store.ensure_runtime()
conn = store.connect_db()
conn.execute(
    """
    INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, started_at)
    VALUES ('run_evt1', 'req_evt1', 'thread_evt1', 'running', 'auto', '2026-01-01T00:00:00+00:00')
    """
)
conn.commit()
conn.close()
print("OK: seeded run")
PY
assert_ok "seed run fixture" test "$STORE_EXIT" -eq 0

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

BASE="http://127.0.0.1:${SOLAR_HOST_PORT}"
assert_ok "host health" curl -sf "${BASE}/health" >/dev/null

CREATE_CODE="$(curl -s -o /tmp/create_appr -w '%{http_code}' -X POST "${BASE}/approvals" \
  -H "Content-Type: application/json" \
  -d '{"run_id":"run_evt1","summary":"needs review"}')"
assert_ok "POST /approvals creates pending" test "$CREATE_CODE" = "201"

SW_CODE="$(curl -s -o /tmp/sw -w '%{http_code}' -X POST "${BASE}/api/workspaces/active" \
  -H "Content-Type: application/json" -d "{\"path\":\"$WS\"}")"
assert_ok "workspace switch emits" test "$SW_CODE" = "200"

APPR_ID="$(python3 -c "import json; print(json.load(open('/tmp/create_appr'))['approval']['approval_id'])")"
REJECT_CODE="$(curl -s -o /tmp/rej -w '%{http_code}' -X POST "${BASE}/api/approvals/${APPR_ID}/reject")"
assert_ok "reject emits resolved" test "$REJECT_CODE" = "200"

curl -sf "${BASE}/api/events?limit=20" >/tmp/host_events_all.json
assert_ok "events include contract types" python3 - "$WS" <<'PY'
import json
import sys

ws = sys.argv[1]
d = json.load(open("/tmp/host_events_all.json"))
types = {e["type"] for e in d.get("events", [])}
assert "approval.pending" in types, types
assert "approval.resolved" in types, types
assert "workspace.activated" in types, types
for e in d["events"]:
    assert e.get("payload", {}).get("workspace") == ws, e
PY

curl -sf "${BASE}/api/events?limit=20&types=approval.pending,approval.resolved" >/tmp/host_events_filtered.json
assert_ok "types filter excludes workspace.activated" python3 <<'PY'
import json

d = json.load(open("/tmp/host_events_filtered.json"))
types = {e["type"] for e in d.get("events", [])}
assert "workspace.activated" not in types, types
assert types <= {"approval.pending", "approval.resolved"}, types
PY

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
