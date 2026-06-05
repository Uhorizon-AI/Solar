#!/usr/bin/env bash
# MVP-b b1: Host API smoke — approvals in-process without legacy :7741 listener.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
IFACE_SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
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
export SOLAR_APP_PORT=19001
export SOLAR_APP_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun"
WS="$(cd "$WS" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

python3 "$SCRIPTS/host_registry.py" add "$WS" "smoke"

STORE_EXIT=0
python3 - <<'PY' "$IFACE_SCRIPTS" "$WS" || STORE_EXIT=$?
import sqlite3
import sys
from pathlib import Path

iface_scripts = Path(sys.argv[1])
ws = sys.argv[2]
sys.path.insert(0, str(iface_scripts))

from interface_store import InterfaceStore

store = InterfaceStore(ws)
store.ensure_runtime()
conn = store.connect_db()
conn.execute(
    """
    INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, started_at)
    VALUES ('run_smoke1', 'req_smoke1', 'thread_smoke1', 'awaiting_approval', 'auto', '2026-01-01T00:00:00+00:00')
    """
)
conn.execute(
    """
    INSERT INTO approvals(approval_id, run_id, status, reason, requested_at)
    VALUES ('appr_smoke1', 'run_smoke1', 'pending', 'test approval', '2026-01-01T00:00:00+00:00')
    """
)
conn.commit()
conn.close()
print("OK: seeded approval")
PY
assert_ok "seed approval fixture" test "$STORE_EXIT" -eq 0

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/health" >/dev/null

APPROVALS="$(curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals")"
assert_ok "approvals JSON" bash -c "echo '$APPROVALS' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert any(a.get('approval_id')=='appr_smoke1' for a in d.get('approvals',[]))\""

REJECT_CODE="$(curl -s -o /tmp/reject_body -w '%{http_code}' -X POST "http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals/appr_smoke1/reject")"
assert_ok "reject approval" test "$REJECT_CODE" = "200"

REMOVED_CODE="$(curl -s -o /tmp/removed_body -w '%{http_code}' -X POST "http://127.0.0.1:${SOLAR_APP_PORT}/api/runtime/interface/start")"
assert_ok "interface/start deprecated" test "$REMOVED_CODE" = "200"
assert_ok "interface/start body" bash -c "python3 -c \"import json; d=json.load(open('/tmp/removed_body')); assert d.get('deprecated') is True and d.get('ok') is True\""

LEGACY_PORT=88099
if lsof -i "tcp:${LEGACY_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "SKIP: legacy port already in use"
else
  assert_ok "no listener on unused legacy port" bash -c "! lsof -i tcp:${LEGACY_PORT} -sTCP:LISTEN >/dev/null 2>&1"
fi

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
