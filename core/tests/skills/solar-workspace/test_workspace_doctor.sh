#!/usr/bin/env bash
# Unit test: solar workspace doctor (minimal fixture).
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
mkdir -p "$INSTALL" "$WS/sun/preferences" "$WS/planets/demo" "$WS/.solar"
touch "$WS/sun/MEMORY.md" "$WS/sun/preferences/profile.md" "$WS/planets/demo/AGENTS.md"
cp -R "$CORE_ROOT" "$INSTALL/core"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$WS/.solar/manifest.json"

export SOLAR_ROOT="$INSTALL"
export SOLAR_WORKSPACE="$WS"

pushd "$WS" >/dev/null
assert_ok "workspace doctor --no-summary" bash "$SOLAR" workspace doctor --no-summary
popd >/dev/null

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
