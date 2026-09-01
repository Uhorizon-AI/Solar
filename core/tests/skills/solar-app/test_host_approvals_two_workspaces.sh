#!/usr/bin/env bash
# MVP-a a4: approvals scoped to active workspace (two workspaces, in-process store).
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
export SOLAR_APP_PORT=19003
export SOLAR_APP_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS_A="$TMP/ws-a"
WS_B="$TMP/ws-b"
mkdir -p "$WS_A/sun" "$WS_B/sun"
WS_A="$(cd "$WS_A" && pwd -P)"
WS_B="$(cd "$WS_B" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi

SEED_EXIT=0
python3 - <<'PY' "$IFACE_SCRIPTS" "$WS_A" "$WS_B" || SEED_EXIT=$?
import sys
from pathlib import Path

iface = Path(sys.argv[1])
ws_a, ws_b = sys.argv[2], sys.argv[3]
sys.path.insert(0, str(iface))

from interface_store import InterfaceStore

for ws, appr_id, run_id in (
    (ws_a, "appr_ws_a", "run_ws_a"),
    (ws_b, "appr_ws_b", "run_ws_b"),
):
    store = InterfaceStore(ws)
    store.ensure_runtime()
    conn = store.connect_db()
    conn.execute(
        """
        INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, started_at)
        VALUES (?, 'req1', 'thread1', 'awaiting_approval', 'auto', '2026-01-01T00:00:00+00:00')
        """,
        (run_id,),
    )
    conn.execute(
        """
        INSERT INTO approvals(approval_id, run_id, status, reason, requested_at)
        VALUES (?, ?, 'pending', 'test', '2026-01-01T00:00:00+00:00')
        """,
        (appr_id, run_id),
    )
    conn.commit()
    conn.close()
print("OK: seeded two workspaces")
PY
assert_ok "seed two workspace approvals" test "$SEED_EXIT" -eq 0

python3 "$SCRIPTS/host_registry.py" add "$WS_A" "a"
python3 "$SCRIPTS/host_registry.py" add "$WS_B" "b"
python3 "$SCRIPTS/host_registry.py" use "$WS_A"

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/health" >/dev/null

curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals" >/tmp/appr_a.json
assert_ok "active WS A sees appr_ws_a only" python3 <<'PY'
import json

d = json.load(open("/tmp/appr_a.json"))
ids = {a.get("approval_id") for a in d.get("approvals", [])}
assert "appr_ws_a" in ids and "appr_ws_b" not in ids, ids
PY

SW_CODE="$(curl -s -o /tmp/sw_body -w '%{http_code}' -X POST "http://127.0.0.1:${SOLAR_APP_PORT}/api/workspaces/active" \
  -H "Content-Type: application/json" -d "{\"path\":\"$WS_B\"}")"
assert_ok "switch to B" test "$SW_CODE" = "200"

curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals" >/tmp/appr_b.json
assert_ok "active WS B sees appr_ws_b only" python3 <<'PY'
import json

d = json.load(open("/tmp/appr_b.json"))
ids = {a.get("approval_id") for a in d.get("approvals", [])}
assert "appr_ws_b" in ids and "appr_ws_a" not in ids, ids
PY

REJECT_CODE="$(curl -s -o /tmp/rej_b -w '%{http_code}' -X POST \
  "http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals/appr_ws_b/reject")"
assert_ok "reject on B" test "$REJECT_CODE" = "200"

SW_A="$(curl -s -o /tmp/sw_a -w '%{http_code}' -X POST "http://127.0.0.1:${SOLAR_APP_PORT}/api/workspaces/active" \
  -H "Content-Type: application/json" -d "{\"path\":\"$WS_A\"}")"
assert_ok "switch back to A" test "$SW_A" = "200"

curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals" >/tmp/appr_a2.json
assert_ok "A approval still pending" python3 <<'PY'
import json

d = json.load(open("/tmp/appr_a2.json"))
row = next(a for a in d.get("approvals", []) if a.get("approval_id") == "appr_ws_a")
assert row.get("status") == "pending", row
PY

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
