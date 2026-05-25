#!/usr/bin/env bash
# smoke-solar-client.sh — go/no-go for Solar Client (manifest + global install).
#
# Usage:
#   bash core/scripts/smoke-solar-client.sh [INSTALL_ROOT]
#
# INSTALL_ROOT = Solar install (parent of core/), default: parent of this script's core/.
# Options:
#   --skip-slow   Skip solar client sync in temp workspace

set -uo pipefail

ROOT=""
SKIP_SLOW=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-slow) SKIP_SLOW=true; shift ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    *)
      ROOT="$1"
      shift
      ;;
  esac
done

if [[ -z "$ROOT" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

SOLAR="$ROOT/core/skills/solar-interface/scripts/solar"
RESOLVE="$ROOT/core/skills/solar-interface/scripts/resolve_solar_paths.sh"
INSTALL_ROOT="$(cd "$ROOT" && pwd -P)"

PASS=0
FAIL=0
SKIP=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "SKIP: $1"; SKIP=$((SKIP + 1)); }

run_expect_ok() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    pass "$label"
  else
    fail "$label"
  fi
}

run_expect_fail() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    fail "$label (expected failure)"
  else
    pass "$label"
  fi
}

_smoke_seed_workspace() {
  local ws="$1"
  mkdir -p "$ws/.solar" "$ws/sun"
  echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$ws/.solar/manifest.json"
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Solar Client go/no-go smoke"
echo "  INSTALL_ROOT=$INSTALL_ROOT"
echo ""

echo "=== Preflight ($INSTALL_ROOT) ==="
[[ -f "$SOLAR" ]] && pass "solar CLI" || fail "solar CLI missing"
[[ -f "$RESOLVE" ]] && pass "resolve_solar_paths.sh" || fail "resolve_solar_paths.sh missing"
run_expect_ok "bash -n solar CLI" bash -n "$SOLAR"
run_expect_ok "bash -n resolve_solar_paths.sh" bash -n "$RESOLVE"

UNIT_RESOLVE="$ROOT/core/tests/skills/solar-interface/test_resolve_solar_paths.sh"
UNIT_PATHS_PY="$ROOT/core/tests/skills/solar-interface/test_solar_paths_py.sh"
if [[ -f "$UNIT_RESOLVE" ]]; then
  bash "$UNIT_RESOLVE" >/dev/null 2>&1 && pass "unit: test_resolve_solar_paths.sh" || fail "unit: test_resolve_solar_paths.sh"
else
  fail "missing test_resolve_solar_paths.sh"
fi
if [[ -f "$UNIT_PATHS_PY" ]]; then
  bash "$UNIT_PATHS_PY" >/dev/null 2>&1 && pass "unit: test_solar_paths_py.sh" || fail "unit: test_solar_paths_py.sh"
else
  skip "test_solar_paths_py.sh not found"
fi

echo "=== Workspace conflict (exported vs cwd) ==="
WS_A="$TMP/workspace-a"
WS_B="$TMP/workspace-b"
_smoke_seed_workspace "$WS_A"
_smoke_seed_workspace "$WS_B"
mkdir -p "$WS_B/nested"
export SOLAR_WORKSPACE="$(cd "$WS_A" && pwd -P)"
if pushd "$WS_B/nested" >/dev/null; then
  run_expect_fail "resolve: export A, cwd B" bash -c "source \"$RESOLVE\" && solar_resolve_paths --quiet"
  popd >/dev/null
else
  fail "could not cd to nested workspace B"
fi
unset SOLAR_WORKSPACE

echo "=== client init (temp) ==="
INIT_WS="$TMP/init-test"
mkdir -p "$INIT_WS"
pushd "$INIT_WS" >/dev/null
if bash "$SOLAR" client init >/dev/null 2>&1; then
  if [[ -f .solar/manifest.json && -d sun && ! -d .solar/core ]]; then
    pass "init: manifest+sun, no .solar/core"
  else
    fail "init: bad layout"
  fi
else
  fail "solar client init"
fi

if bash "$SOLAR" paths 2>/dev/null | grep -q '@core/skills/'; then
  pass "paths: @core/skills/"
else
  fail "paths: missing @core/skills/"
fi

marker="SMOKE_$(date +%s)"
echo "SMOKE_MARKER=$marker" >> .env
if bash "$SOLAR" client init >/dev/null 2>&1 && grep -q "SMOKE_MARKER=$marker" .env; then
  pass "re-init preserves .env"
else
  fail "re-init overwrote .env"
fi

run_expect_ok "solar status after init" bash "$SOLAR" status
run_expect_ok "solar client doctor after init" bash "$SOLAR" client doctor

if [[ "$SKIP_SLOW" != true ]]; then
  run_expect_ok "solar client sync after init" bash "$SOLAR" client sync
else
  skip "client sync (--skip-slow)"
fi
popd >/dev/null

echo "=== client upgrade ==="
UPG_WS="$TMP/upgrade-test"
_smoke_seed_workspace "$UPG_WS"
mkdir -p "$UPG_WS/.solar/core/skills"
touch "$UPG_WS/.solar/.env"
echo '{"layout":"solar-client-v1"}' > "$UPG_WS/.solar/manifest.json"
pushd "$UPG_WS" >/dev/null
if bash "$SOLAR" client upgrade >/dev/null 2>&1; then
  layout="$(python3 -c 'import json; print(json.load(open(".solar/manifest.json")).get("layout",""))')"
  if [[ ! -d .solar/core && "$layout" == "solar-client-v1.1" ]]; then
    pass "upgrade: removes .solar/core, v1.1 manifest"
  else
    fail "upgrade: layout or .solar/core"
  fi
else
  fail "solar client upgrade"
fi

root_line="$(bash "$SOLAR" paths 2>/dev/null | grep '^SOLAR_ROOT=' || true)"
if [[ -n "$root_line" && "$root_line" == *"$INSTALL_ROOT"* ]]; then
  pass "paths: SOLAR_ROOT = install root"
else
  fail "paths: SOLAR_ROOT ($root_line)"
fi
run_expect_ok "status after upgrade" bash "$SOLAR" status
popd >/dev/null

echo "=== doctor blocks obsolete .solar/core ==="
BLOCK_WS="$TMP/block-test"
_smoke_seed_workspace "$BLOCK_WS"
mkdir -p "$BLOCK_WS/.solar/core"
echo '{"layout":"solar-client-v1"}' > "$BLOCK_WS/.solar/manifest.json"
pushd "$BLOCK_WS" >/dev/null
doc_out="$(bash "$SOLAR" client doctor 2>&1 || true)"
if echo "$doc_out" | grep -qi "upgrade"; then
  pass "doctor hints upgrade when .solar/core present"
else
  fail "doctor upgrade hint (got: $doc_out)"
fi
popd >/dev/null

echo ""
echo "=== Go / No-Go ==="
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
if [[ "$FAIL" -gt 0 ]]; then
  echo "NO-GO: $FAIL failure(s). Search for 'FAIL:' above." >&2
  exit 1
fi
echo "GO: Solar Client smoke checks passed ($PASS checks)."
exit 0
