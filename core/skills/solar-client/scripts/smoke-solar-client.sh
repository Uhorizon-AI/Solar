#!/usr/bin/env bash
# smoke-solar-client.sh — go/no-go for Solar Client (manifest + global install).
#
# Usage:
#   bash core/skills/solar-client/scripts/smoke-solar-client.sh [INSTALL_ROOT]
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
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
else
  ROOT="$(cd "$ROOT" && pwd -P)"
fi

INSTALL_ROOT="$ROOT"
SOLAR="$INSTALL_ROOT/core/skills/solar-client/scripts/solar"
RESOLVE="$INSTALL_ROOT/core/skills/solar-paths/scripts/resolve_solar_paths.sh"

PASS=0
FAIL=0
SKIP=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "SKIP: $1"; SKIP=$((SKIP + 1)); }

run_expect_ok() {
  local label="$1"
  shift
  if "$@" >"$TMP/command.log" 2>&1; then
    pass "$label"
  else
    cat "$TMP/command.log" >&2
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
  echo '{"layout":"solar-client-v1.1","core_source":"global","requires_global_client":true,"portable_capabilities":[]}' > "$ws/.solar/manifest.json"
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Do not inherit production roots, cutover hooks or provider configuration.
for smoke_var in ${!SOLAR_@}; do unset "$smoke_var"; done
mkdir -p "$TMP/bin" "$TMP/install"
# Exercise a disposable copy, including upgrade's install-pruning path.
SOURCE_ROOT="$INSTALL_ROOT"
mkdir -p "$TMP/install/core"
(cd "$SOURCE_ROOT/core" && tar --exclude='.venv' --exclude='__pycache__' -cf - .) | \
  tar -xf - -C "$TMP/install/core" || exit 1
INSTALL_ROOT="$TMP/install"
SOLAR="$INSTALL_ROOT/core/skills/solar-client/scripts/solar"
RESOLVE="$INSTALL_ROOT/core/skills/solar-paths/scripts/resolve_solar_paths.sh"
cat >"$TMP/bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
# The smoke is offline. Individual unit tests install their own response doubles.
exit 1
EOF
chmod +x "$TMP/bin/launchctl" "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/bin/launchctl"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none
: >"$TMP/empty-ps"
export SOLAR_CLIENT_PS_OUTPUT_FILE="$TMP/empty-ps"
export SOLAR_CUTOVER_PS_OUTPUT_FILE="$TMP/empty-ps"
source "$INSTALL_ROOT/core/tests/support/shell_runtime_guard.sh" || exit 1

_smoke_context() {
  local name="$1" install="${2:-$INSTALL_ROOT}"
  export SOLAR_ROOT="$install" SOLAR_INSTALL_DIR="$install"
  export SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$install"
  export SOLAR_APP_DATA="$TMP/$name-app" SOLAR_RUNTIME_ROOT="$TMP/$name-runtime"
  solar_test_guard --services
}

_smoke_unit() (
  # Unit fixtures select their own installs and workspaces.
  unset SOLAR_ROOT SOLAR_INSTALL_DIR SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE SOLAR_WORKSPACE
  # Historical updater regressions need the source repository's release tags.
  bash "$SOURCE_ROOT/${1#"$INSTALL_ROOT/"}"
)
_smoke_context preflight

echo "Solar Client go/no-go smoke"
echo "  SOURCE_ROOT=$SOURCE_ROOT"
echo "  INSTALL_ROOT=$INSTALL_ROOT (disposable copy)"
echo ""

echo "=== Preflight ($INSTALL_ROOT) ==="
[[ -f "$SOLAR" ]] && pass "solar CLI" || fail "solar CLI missing"
[[ -f "$RESOLVE" ]] && pass "resolve_solar_paths.sh" || fail "resolve_solar_paths.sh missing"
run_expect_ok "bash -n solar CLI" bash -n "$SOLAR"
run_expect_ok "bash -n resolve_solar_paths.sh" bash -n "$RESOLVE"

UNIT_RESOLVE="$INSTALL_ROOT/core/tests/skills/solar-paths/test_resolve_solar_paths.sh"
UNIT_PATHS_PY="$INSTALL_ROOT/core/tests/skills/solar-paths/test_solar_paths_py.sh"
UNIT_UPGRADE="$INSTALL_ROOT/core/tests/skills/solar-client/test_client_upgrade.sh"
UNIT_MANIFEST="$INSTALL_ROOT/core/tests/skills/solar-client/test_client_manifest.sh"
UNIT_BUNDLE="$INSTALL_ROOT/core/tests/skills/solar-client/test_client_bundle.sh"
UNIT_SYNC_EXCLUDE="$INSTALL_ROOT/core/tests/skills/solar-client/test_sync_exclude.sh"
UNIT_SYNC_CODEX_AGENTS="$INSTALL_ROOT/core/tests/skills/solar-client/test_sync_codex_agents.sh"
UNIT_DOCTOR_PORT="$INSTALL_ROOT/core/tests/skills/solar-client/test_doctor_port.sh"
if [[ -f "$UNIT_RESOLVE" ]]; then
  run_expect_ok "unit: test_resolve_solar_paths.sh" _smoke_unit "$UNIT_RESOLVE"
else
  fail "missing test_resolve_solar_paths.sh"
fi
if [[ -f "$UNIT_PATHS_PY" ]]; then
  run_expect_ok "unit: test_solar_paths_py.sh" _smoke_unit "$UNIT_PATHS_PY"
else
  skip "test_solar_paths_py.sh not found"
fi
if [[ -f "$UNIT_UPGRADE" ]]; then
  run_expect_ok "unit: test_client_upgrade.sh" _smoke_unit "$UNIT_UPGRADE"
else
  fail "missing test_client_upgrade.sh"
fi
if [[ -f "$UNIT_MANIFEST" ]]; then
  run_expect_ok "unit: test_client_manifest.sh" _smoke_unit "$UNIT_MANIFEST"
else
  fail "missing test_client_manifest.sh"
fi
if [[ -f "$UNIT_BUNDLE" ]]; then
  run_expect_ok "unit: test_client_bundle.sh" _smoke_unit "$UNIT_BUNDLE"
else
  fail "missing test_client_bundle.sh"
fi
if [[ -f "$UNIT_SYNC_EXCLUDE" ]]; then
  run_expect_ok "unit: test_sync_exclude.sh" _smoke_unit "$UNIT_SYNC_EXCLUDE"
else
  fail "missing test_sync_exclude.sh"
fi
if [[ -f "$UNIT_SYNC_CODEX_AGENTS" ]]; then
  run_expect_ok "unit: test_sync_codex_agents.sh" _smoke_unit "$UNIT_SYNC_CODEX_AGENTS"
else
  fail "missing test_sync_codex_agents.sh"
fi
if [[ -f "$UNIT_DOCTOR_PORT" ]]; then
  run_expect_ok "unit: test_doctor_port.sh" _smoke_unit "$UNIT_DOCTOR_PORT"
else
  skip "test_doctor_port.sh not found"
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
_smoke_context init
pushd "$INIT_WS" >/dev/null
if bash "$SOLAR" client init >"$TMP/command.log" 2>&1; then
  if [[ -f .solar/settings.json && -d sun && ! -d .solar/core ]]; then
    pass "init: settings+sun, no .solar/core"
  else
    fail "init: bad layout"
  fi
else
  cat "$TMP/command.log" >&2
  fail "solar client init"
fi

if bash "$SOLAR" paths 2>/dev/null | grep -q '@core/skills/'; then
  pass "paths: @core/skills/"
else
  fail "paths: missing @core/skills/"
fi

marker="SMOKE_$(date +%s)"
echo "SMOKE_MARKER=$marker" >> .env
run_expect_ok "solar client re-init" bash "$SOLAR" client init
if grep -q "SMOKE_MARKER=$marker" .env; then
  pass "re-init preserves .env"
else
  fail "re-init overwrote .env"
fi

status_out="$(bash "$SOLAR" status 2>&1 || true)"
if echo "$status_out" | grep -q "core_source=global"; then
  pass "solar status reads settings after init"
else
  fail "solar status reads settings after init"
fi
doc_out="$(bash "$SOLAR" client doctor 2>&1 || true)"
if echo "$doc_out" | grep -q "settings core_source=global"; then
  pass "doctor reports core_source=global"
  pass "solar client doctor after init"
else
  fail "doctor core_source global hint"
  echo "$doc_out" | grep -E 'core_source|ERROR|FAIL' || true
  fail "solar client doctor after init"
fi

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
_smoke_context upgrade
pushd "$UPG_WS" >/dev/null
if bash "$SOLAR" client upgrade >/dev/null 2>&1; then
  layout="$(python3 -c 'import json; print(json.load(open(".solar/settings.json")).get("layout",""))')"
  if [[ ! -d .solar/core && ! -f .solar/manifest.json && "$layout" == "solar-client-v1.2" ]]; then
    pass "upgrade: removes .solar/core, writes v1.2 settings"
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
status_out="$(bash "$SOLAR" status 2>&1 || true)"
if echo "$status_out" | grep -q "core_source=global"; then
  pass "solar status reads settings after upgrade"
else
  fail "solar status reads settings after upgrade"
fi
popd >/dev/null

echo "=== doctor blocks obsolete .solar/core ==="
BLOCK_WS="$TMP/block-test"
_smoke_seed_workspace "$BLOCK_WS"
mkdir -p "$BLOCK_WS/.solar/core"
echo '{"layout":"solar-client-v1"}' > "$BLOCK_WS/.solar/manifest.json"
_smoke_context block
pushd "$BLOCK_WS" >/dev/null
doc_out="$(bash "$SOLAR" client doctor 2>&1 || true)"
if echo "$doc_out" | grep -qi "upgrade"; then
  pass "doctor hints upgrade when .solar/core present"
else
  fail "doctor upgrade hint (got: $doc_out)"
fi
popd >/dev/null

echo "=== upgrade prune install (temp) ==="
PRUNE_INSTALL="$TMP/prune-install"
PRUNE_WS="$TMP/prune-ws"
mkdir -p "$PRUNE_INSTALL" "$PRUNE_WS/sun" "$PRUNE_WS/.solar"
cp -R "$INSTALL_ROOT/core" "$PRUNE_INSTALL/core"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$PRUNE_WS/.solar/manifest.json"
mkdir -p "$PRUNE_INSTALL/.cursor/skills/smoke-dummy"
PRUNE_SOLAR="$PRUNE_INSTALL/core/skills/solar-client/scripts/solar"
_smoke_context prune "$PRUNE_INSTALL"
pushd "$PRUNE_WS" >/dev/null
if bash "$PRUNE_SOLAR" client upgrade >/dev/null 2>&1; then
  if [[ ! -d "$PRUNE_INSTALL/.cursor" ]]; then
    pass "upgrade: pruned .cursor from isolated install"
  else
    fail "upgrade: .cursor still on install mimic"
  fi
else
  fail "solar client upgrade on prune fixture"
fi
popd >/dev/null

_smoke_context init
if [[ -d "$SOURCE_ROOT/.cursor/skills" ]]; then
  skip "INSTALL_ROOT still has .cursor/ (run: solar client upgrade from ~/Solar)"
else
  pass "INSTALL_ROOT has no .cursor/skills"
fi

echo "=== client update --check ==="
pushd "$INIT_WS" >/dev/null
run_expect_ok "update --check" bash "$SOLAR" client update --check
popd >/dev/null

echo "=== client update unit test ==="
UPDATE_TEST="$INSTALL_ROOT/core/tests/skills/solar-client/test_client_update.sh"
if [[ -f "$UPDATE_TEST" ]]; then
  run_expect_ok "unit: test_client_update.sh" _smoke_unit "$UPDATE_TEST"
else
  fail "test_client_update.sh missing"
fi

echo "=== client update --bundle (temp install) ==="
BUNDLE_INSTALL="$TMP/bundle-install"
BUNDLE_WS="$TMP/bundle-ws"
mkdir -p "$BUNDLE_INSTALL/core" "$BUNDLE_WS/sun" "$BUNDLE_WS/.solar"
cp -R "$INSTALL_ROOT/core/skills" "$BUNDLE_INSTALL/core/"
cp -R "$INSTALL_ROOT/core/scripts" "$BUNDLE_INSTALL/core/"
cp -R "$INSTALL_ROOT/core/agents" "$BUNDLE_INSTALL/core/" 2>/dev/null || mkdir -p "$BUNDLE_INSTALL/core/agents"
cp -R "$INSTALL_ROOT/core/commands" "$BUNDLE_INSTALL/core/" 2>/dev/null || mkdir -p "$BUNDLE_INSTALL/core/commands"
cp -R "$INSTALL_ROOT/core/templates" "$BUNDLE_INSTALL/core/" 2>/dev/null || mkdir -p "$BUNDLE_INSTALL/core/templates"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$BUNDLE_WS/.solar/manifest.json"
echo "before-bundle" > "$BUNDLE_INSTALL/core/.marker"
BUNDLE_SOLAR="$BUNDLE_INSTALL/core/skills/solar-client/scripts/solar"
_smoke_context bundle "$BUNDLE_INSTALL"
pushd "$BUNDLE_WS" >/dev/null
run_expect_ok "update --bundle on install without .git" bash "$BUNDLE_SOLAR" client update --bundle --yes
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
