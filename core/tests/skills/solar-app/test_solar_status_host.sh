#!/usr/bin/env bash
# test_solar_status_host.sh — solar status host block + router stale age filter.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SOLAR="$ROOT/skills/solar-client/scripts/solar"
ROUTER="$ROOT/skills/solar-router/scripts"
STATE_SCRIPTS="$ROOT/skills/solar-state/scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=../../support/shell_runtime_guard.sh
source "$ROOT/tests/support/shell_runtime_guard.sh"
mkdir -p "$TMP/guard-bin"
cat >"$TMP/guard-bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/guard-bin/launchctl"
export PATH="$TMP/guard-bin:${PATH}"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl"
unset SOLAR_RUNTIME_ROOT

pass=0
fail=0
pass() { echo "PASS: $1"; pass=$((pass + 1)); }
fail() { echo "FAIL: $1"; fail=$((fail + 1)); }

# Machine state lives outside the workspace. The runtime is sqlite and has an
# owner; audit rows are written by solar-state, not as router/audit.jsonl.
export SOLAR_APP_DATA="$TMP/AppData"
export SOLAR_WORKSPACE="$TMP"
solar_test_guard
WS_ID="status-host-ws"
mkdir -p "$TMP/sun/preferences" "$TMP/.solar" "$TMP/planets"
touch "$TMP/sun/preferences/profile.md" "$TMP/sun/MEMORY.md"
cat >"$TMP/.solar/settings.json" <<EOF
{
  "layout": "solar-client-v1.2",
  "scope": "workspace",
  "core_source": "global",
  "workspace_id": "$WS_ID"
}
EOF
old_ts="2026-01-01T00:00:00+00:00"
recent_ts="$(python3 - <<'PY'
from datetime import datetime, timezone, timedelta
print((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
PY
)"
STATE_SCRIPTS="$STATE_SCRIPTS" WS_ID="$WS_ID" OLD_TS="$old_ts" RECENT_TS="$recent_ts" python3 - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ["STATE_SCRIPTS"])
import solar_state
ws = Path(os.environ["SOLAR_WORKSPACE"])
solar_state.claim_owner(ws, os.environ["WS_ID"])
rows = [
    {"ts": os.environ["OLD_TS"], "event": "start", "router_id": "old-orphan", "request_id": "t1", "user_id": "u"},
    {"ts": os.environ["RECENT_TS"], "event": "start", "router_id": "new-orphan", "request_id": "t2", "user_id": "u"},
]
with solar_state.cutover() as cut:
    cut.upgrade_schema()
    cut.set_format(solar_state.FORMAT_SQLITE)
with solar_state.session() as store:
    for row in rows:
        store.audit_append(row)
import solar_runtime
runtime = solar_runtime.runtime_root()
jsonl = runtime / "router" / "audit.jsonl"
if jsonl.exists():
    raise SystemExit(f"audit was written to {jsonl}")
PY

export SOLAR_ROOT="$ROOT/.."
pushd "$TMP" >/dev/null
recent="$(bash "$ROUTER/status_router.sh" --stale-count 2>/dev/null || echo 0)"
all="$(bash "$ROUTER/status_router.sh" --stale-count-all 2>/dev/null || echo 0)"
if [[ "$recent" == "1" && "$all" == "2" ]]; then
  pass "stale-count age filter (recent=1 all=2)"
else
  fail "stale-count age filter" "recent=$recent all=$all"
fi

bash "$ROUTER/reconcile_router_audit.sh" --min-age-hours 0 >/dev/null
after="$(bash "$ROUTER/status_router.sh" --stale-count-all 2>/dev/null || echo 0)"
popd >/dev/null
if [[ "$after" == "0" ]]; then
  pass "reconcile_router_audit closes orphans"
else
  fail "reconcile_router_audit" "stale_all=$after after reconcile"
fi

# Another owner is a refusal, not a count of zero.
OTHER="$TMP/other-owner"
mkdir -p "$OTHER/sun" "$OTHER/.solar"
cat >"$OTHER/.solar/settings.json" <<'EOF'
{
  "layout": "solar-client-v1.2",
  "scope": "workspace",
  "core_source": "global",
  "workspace_id": "someone-else"
}
EOF
set +e
foreign_out="$(
  cd "$OTHER"
  unset SOLAR_WORKSPACE
  bash "$ROUTER/status_router.sh" --stale-count 2>"$TMP/foreign.err"
)"
foreign_ec=$?
set -e
if [[ "$foreign_ec" -ne 0 && "$foreign_out" != "0" ]] && grep -q 'status-host-ws' "$TMP/foreign.err"; then
  pass "stale-count refuses a runtime owned by someone else"
else
  fail "stale-count other owner" "ec=$foreign_ec out='$foreign_out' err=$(cat "$TMP/foreign.err" 2>/dev/null || true)"
fi

status_json="$(
  cd "$OTHER"
  unset SOLAR_WORKSPACE
  bash "$SOLAR" status --json
)"
status_router_state="$(printf '%s\n' "$status_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("router",""))')"
status_router_detail="$(printf '%s\n' "$status_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("router_detail",""))')"
if [[ "$status_router_state" == "WARN" && "$status_router_detail" == "unknown (state refused:"* && "$status_router_detail" == *"status-host-ws"* ]]; then
  pass "solar status --json reports unknown when the runtime has another owner"
else
  fail "solar status other owner" "router=$status_router_state detail=$status_router_detail"
fi

# solar status JSON uses host key. Opt-in smoke on a real workspace:
#   SOLAR_SMOKE_WORKSPACE=/path/to/workspace bash test_solar_status_host.sh
SMOKE_WS="${SOLAR_SMOKE_WORKSPACE:-}"
if [[ -n "$SMOKE_WS" && -d "$SMOKE_WS/.solar" ]]; then
  out="$(cd "$SMOKE_WS" && bash "$SOLAR" status --json 2>/dev/null || true)"
  if echo "$out" | grep -q '"host"'; then
    pass "solar status --json has host block"
  else
    fail "solar status --json host block"
  fi
  if echo "$out" | grep -q '"interface"'; then
    fail "solar status --json still has deprecated interface key"
  else
    pass "solar status --json no legacy interface key"
  fi
fi

echo "=== $pass passed, $fail failed ==="
[[ "$fail" -eq 0 ]]
