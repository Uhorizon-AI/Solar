#!/usr/bin/env bash
# test_solar_status_host.sh — solar status host block + router stale age filter.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SOLAR="$ROOT/skills/solar-client/scripts/solar"
ROUTER="$ROOT/skills/solar-router/scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
pass() { echo "PASS: $1"; pass=$((pass + 1)); }
fail() { echo "FAIL: $1"; fail=$((fail + 1)); }

mkdir -p "$TMP/sun/runtime/router"
AUDIT="$TMP/sun/runtime/router"
mkdir -p "$TMP/sun/preferences" "$TMP/.solar" "$TMP/planets"
touch "$TMP/sun/preferences/profile.md" "$TMP/sun/MEMORY.md"
echo '{"layout":"solar-client-v1"}' >"$TMP/.solar/manifest.json"
old_ts="2026-01-01T00:00:00+00:00"
recent_ts="$(python3 - <<'PY'
from datetime import datetime, timezone, timedelta
print((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
PY
)"
cat >"$AUDIT/audit.jsonl" <<EOF
{"ts":"$old_ts","event":"start","router_id":"old-orphan","request_id":"t1","user_id":"u"}
{"ts":"$recent_ts","event":"start","router_id":"new-orphan","request_id":"t2","user_id":"u"}
EOF

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

# solar status JSON uses host key (smoke on real workspace if host up)
if [[ -d "/Users/louisjimenezp/Solar/.solar" ]]; then
  out="$(cd /Users/louisjimenezp/Solar && bash "$SOLAR" status --json 2>/dev/null || true)"
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
