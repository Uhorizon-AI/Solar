#!/usr/bin/env bash
# test_onboard_agy_migration.sh — GEMINI → agy onboard rules (no blind CMD copy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ONBOARD="$ROOT/skills/solar-router/scripts/onboard_router_env.sh"
MIGRATE_PY="$ROOT/skills/solar-router/scripts/migrate_provider_priority.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
pass() { echo "PASS: $1"; pass=$((pass + 1)); }
fail() { echo "FAIL: $1"; fail=$((fail + 1)); }

# --- helper §F cases ---
assert_migrate() {
  local input="$1" expected="$2" label="$3"
  local got
  got="$(python3 "$MIGRATE_PY" "$input" | tr -d '\n')"
  if [[ "$got" == "$expected" ]]; then
    pass "helper: $label"
  else
    fail "helper: $label (got=$got expected=$expected)"
  fi
}

assert_migrate "gemini" "agy" "gemini alone"
assert_migrate "gemini,gemini" "agy" "gemini,gemini"
assert_migrate "codex,gemini,gemini,claude" "codex,agy,claude" "mixed duplicates"
assert_migrate "GEMINI,codex" "agy,codex" "case insensitive"
assert_migrate "codex,claude,agy" "codex,claude,agy" "noop canonical"
assert_migrate " codex , , gemini , " "codex,agy" "whitespace/empty"

# --- onboard integration ---
cd "$TMP"
cat >.env <<'EOF'
# [solar-router] required environment
SOLAR_ROUTER_PROVIDER_PRIORITY=gemini,codex
SOLAR_ROUTER_GEMINI_CMD=gemini -y -m gemini-3-flash -p
EOF

out="$(bash "$ONBOARD" 2>&1)" || true

if echo "$out" | grep -qi "migrated SOLAR_ROUTER_PROVIDER_PRIORITY"; then
  pass "onboard warns and rewrites gemini token in priority"
else
  fail "missing gemini→agy priority rewrite warn (out=$out)"
fi

if grep -Eq '^SOLAR_ROUTER_PROVIDER_PRIORITY=.*agy' .env \
  && ! grep -Eq '^SOLAR_ROUTER_PROVIDER_PRIORITY=.*gemini' .env; then
  pass "priority written with agy, without gemini"
else
  fail "priority not migrated: $(grep SOLAR_ROUTER_PROVIDER_PRIORITY .env || true)"
fi

if echo "$out" | grep -qi "was NOT copied"; then
  pass "GEMINI_CMD not blindly copied"
else
  fail "expected NOT copied warn for GEMINI_CMD"
fi

if grep -Eq '^SOLAR_ROUTER_AGY_CMD=gemini' .env; then
  fail "invalid SOLAR_ROUTER_AGY_CMD=gemini... was written"
elif grep -Eq '^SOLAR_ROUTER_AGY_CMD=' .env; then
  fail "unexpected SOLAR_ROUTER_AGY_CMD written from legacy value"
else
  pass "no SOLAR_ROUTER_AGY_CMD created from legacy GEMINI_CMD"
fi

echo "=== $pass passed, $fail failed ==="
[[ "$fail" -eq 0 ]]
