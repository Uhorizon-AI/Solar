#!/usr/bin/env bash
# Unit tests for client upgrade (Fase 1.2: install prune, report).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
UPGRADE="$CORE_ROOT/skills/solar-interface/scripts/client_upgrade.sh"
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

assert_fail() {
  local label="$1"
  shift
  if "$@"; then
    echo "FAIL: $label (expected failure)" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $label"
    PASS=$((PASS + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

INSTALL="$TMP/install"
WS="$TMP/workspace"
mkdir -p "$INSTALL" "$WS/sun" "$WS/.solar"
cp -R "$CORE_ROOT" "$INSTALL/core"
INSTALL_SOLAR="$INSTALL/core/skills/solar-interface/scripts/solar"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$WS/.solar/manifest.json"
mkdir -p "$INSTALL/.cursor/skills/dummy-skill"

# shellcheck source=/dev/null
source "$INSTALL/core/skills/solar-interface/scripts/client_lib.sh"

assert_ok "paths_equal same dir" solar_client_paths_equal "$TMP" "$TMP"
assert_fail "paths_equal different" solar_client_paths_equal "$INSTALL" "$WS"

artifacts="$(solar_client_list_install_artifacts "$INSTALL")"
assert_ok "lists install artifact" test -n "$artifacts"
assert_ok "artifact is .cursor" test -d "$INSTALL/.cursor/skills/dummy-skill"

pushd "$WS" >/dev/null
out_check="$(bash "$INSTALL_SOLAR" client upgrade --check 2>&1)" || true
popd >/dev/null
assert_ok "upgrade --check mentions prune" bash -c "printf '%s' \"$out_check\" | grep -q 'prune install'"
assert_ok "upgrade --check leaves dummy" test -d "$INSTALL/.cursor/skills/dummy-skill"

pushd "$WS" >/dev/null
bash "$INSTALL_SOLAR" client upgrade --skip-prune-install >/dev/null 2>&1
popd >/dev/null
assert_ok "skip-prune leaves dummy" test -d "$INSTALL/.cursor/skills/dummy-skill"

mkdir -p "$INSTALL/.cursor/skills/dummy-skill2"

pushd "$WS" >/dev/null
bash "$INSTALL_SOLAR" client upgrade >/dev/null 2>&1
popd >/dev/null
assert_ok "upgrade prunes .cursor" test ! -d "$INSTALL/.cursor"
assert_ok "upgrade keeps core/" test -f "$INSTALL/core/skills/solar-interface/scripts/solar"

echo "---"
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
