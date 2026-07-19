#!/usr/bin/env bash
# test_migrate_workspace_env_agy.sh — atomic .env priority migration (gemini→agy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
MIGRATE="$ROOT/skills/solar-client/scripts/migrate_workspace_env_agy.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
pass() { echo "PASS: $1"; pass=$((pass + 1)); }
fail() { echo "FAIL: $1"; fail=$((fail + 1)); }

ENV_FILE="$TMP/.env"
chmod_mode=0640

cat >"$ENV_FILE" <<'EOF'
# keep this comment
FOO=bar

# [solar-router] required environment
SOLAR_ROUTER_PROVIDER_PRIORITY=gemini,codex
SOLAR_ROUTER_GEMINI_CMD=gemini -y -m gemini-3-flash -p
# trailing comment
EOF
chmod "$chmod_mode" "$ENV_FILE"
before_mode="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")"

out="$(python3 "$MIGRATE" "$ENV_FILE" 2>&1)" || { fail "migrator exit non-zero: $out"; echo "=== abort ==="; exit 1; }

if echo "$out" | grep -q 'SOLAR_ROUTER_PROVIDER_PRIORITY:.*gemini.*->.*agy'; then
  pass "stdout reports before -> after"
else
  fail "missing before→after summary (out=$out)"
fi

if echo "$out" | grep -qi 'remove SOLAR_ROUTER_GEMINI_CMD'; then
  pass "WARN to remove GEMINI_CMD (no rename)"
else
  fail "missing GEMINI_CMD remove warn (out=$out)"
fi

if grep -Eq '^SOLAR_ROUTER_PROVIDER_PRIORITY=agy,codex$' "$ENV_FILE"; then
  pass "priority migrated to agy,codex"
else
  fail "bad priority: $(grep PROVIDER_PRIORITY "$ENV_FILE" || true)"
fi

if grep -Eq '^# keep this comment$' "$ENV_FILE" \
  && grep -Eq '^FOO=bar$' "$ENV_FILE" \
  && grep -Eq '^# trailing comment$' "$ENV_FILE"; then
  pass "comments and unrelated keys intact"
else
  fail "comments/keys altered"
fi

if grep -Eq '^SOLAR_ROUTER_GEMINI_CMD=gemini' "$ENV_FILE"; then
  pass "GEMINI_CMD left untouched (not renamed)"
else
  fail "GEMINI_CMD was modified unexpectedly"
fi

after_mode="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")"
if [[ "$before_mode" == "$after_mode" ]]; then
  pass "file mode preserved ($after_mode)"
else
  fail "mode changed $before_mode → $after_mode"
fi

# no-op second run
out2="$(python3 "$MIGRATE" "$ENV_FILE" 2>&1)" || true
if echo "$out2" | grep -qx 'no-op' || echo "$out2" | grep -q '^no-op$'; then
  pass "second run is no-op for priority"
else
  # may still WARN about GEMINI_CMD on stderr mixed — accept if priority unchanged
  if grep -Eq '^SOLAR_ROUTER_PROVIDER_PRIORITY=agy,codex$' "$ENV_FILE" && echo "$out2" | grep -qi 'no-op'; then
    pass "second run is no-op for priority"
  else
    fail "expected no-op (out2=$out2)"
  fi
fi

# abort: unreadable path
if python3 "$MIGRATE" "$TMP/missing.env" >/dev/null 2>&1; then
  fail "missing .env should exit 1"
else
  pass "missing .env exits non-zero"
fi

# atomic replace: directory must not leave .env.agy.* leftovers after success
leftovers="$(find "$TMP" -name '.env.agy.*' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$leftovers" == "0" ]]; then
  pass "no temp leftovers after atomic replace"
else
  fail "temp leftovers remain: $(find "$TMP" -name '.env.agy.*')"
fi

echo "=== $pass passed, $fail failed ==="
[[ "$fail" -eq 0 ]]
