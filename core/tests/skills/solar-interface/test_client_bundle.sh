#!/usr/bin/env bash
# Unit tests for workspace portable bundle (Fase 3B).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SOLAR="$CORE_ROOT/skills/solar-interface/scripts/solar"
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
trap 'rm -rf "$TMP"' EXIT

INSTALL="$TMP/install"
WS="$TMP/workspace"
mkdir -p "$INSTALL" "$WS/sun/preferences" "$WS/planets" "$WS/.solar"
touch "$WS/sun/MEMORY.md" "$WS/sun/preferences/profile.md"
cp -R "$CORE_ROOT" "$INSTALL/core"
echo '{"layout":"solar-client-v1.1","core_source":"global","requires_global_client":true}' > "$WS/.solar/manifest.json"

export SOLAR_ROOT="$INSTALL"
export SOLAR_WORKSPACE="$WS"

pushd "$WS" >/dev/null
assert_ok "bundle create" bash "$SOLAR" client bundle create
assert_ok "manifest portable" grep -q workspace-snapshot .solar/manifest.json
assert_ok "bundle index exists" test -f .solar/bundle/index.json
assert_ok "bundle verify" bash "$SOLAR" client bundle verify

assert_ok "bundle create refresh (portable)" bash "$SOLAR" client bundle create
assert_ok "bundle refresh index exists" test -f .solar/bundle/index.json

doc_refresh="$(bash "$SOLAR" client doctor 2>&1 || true)"
assert_ok "doctor no secret scan noise" bash -c "! echo \"$doc_refresh\" | grep -q 'bundle secret scan'"

unset SOLAR_ROOT SOLAR_WORKSPACE
assert_ok "resolve portable without global install" bash -c "
  source \"$INSTALL/core/skills/solar-interface/scripts/resolve_solar_paths.sh\"
  solar_resolve_paths --workspace \"$WS\" --quiet
  got=\"\$(solar_core_dir)\"
  want=\"$WS/.solar/bundle/core\"
  python3 -c 'import os,sys; sys.exit(0 if os.path.realpath(sys.argv[1])==os.path.realpath(sys.argv[2]) else 1)' \"\$got\" \"\$want\"
"

assert_ok "doctor portable without global" bash "$SOLAR" client doctor
popd >/dev/null

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
