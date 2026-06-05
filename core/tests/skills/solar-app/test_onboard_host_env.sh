#!/usr/bin/env bash
# test_onboard_host_env.sh — onboarding migrates legacy keys, does not clobber values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ONBOARD="$CORE_ROOT/skills/solar-app/scripts/onboard_host_env.sh"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/.solar"
echo '{"layout":"solar-client-v1.1"}' >"$WS/.solar/manifest.json"

cat >"$WS/.env" <<'EOF'
# other
FOO=bar
SOLAR_HOST_HOST=127.0.0.8
SOLAR_HOST_PORT=8811
EOF

(
  cd "$WS"
  export SOLAR_WORKSPACE="$WS"
  bash "$ONBOARD" >/dev/null
)

if grep -q '^SOLAR_HOST_HOST=' "$WS/.env" || grep -q '^SOLAR_HOST_PORT=' "$WS/.env"; then
  fail "legacy keys should be removed after onboard"
else
  pass "legacy keys removed"
fi

if grep -q '^SOLAR_APP_HOST=127.0.0.8$' "$WS/.env" && grep -q '^SOLAR_APP_PORT=8811$' "$WS/.env"; then
  pass "legacy values migrated to SOLAR_APP_*"
else
  fail "expected SOLAR_APP_HOST=127.0.0.8 and SOLAR_APP_PORT=8811"
  grep '^SOLAR_APP_' "$WS/.env" >&2 || true
fi

# Fresh onboard keeps defaults when no prior config.
WS2="$TMP/ws2"
mkdir -p "$WS2/sun" "$WS2/.solar"
echo '{"layout":"solar-client-v1.1"}' >"$WS2/.solar/manifest.json"
: >"$WS2/.env"
(
  cd "$WS2"
  export SOLAR_WORKSPACE="$WS2"
  bash "$ONBOARD" >/dev/null
)
if grep -q '^SOLAR_APP_HOST=127.0.0.1$' "$WS2/.env" && grep -q '^SOLAR_APP_PORT=9000$' "$WS2/.env"; then
  pass "defaults for empty workspace"
else
  fail "expected defaults 127.0.0.1:9000 on empty onboard"
fi

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
