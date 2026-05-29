#!/usr/bin/env bash
# Unit tests for manifest dual-mode contract (Fase 3A).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# shellcheck source=/dev/null
source "$CORE_ROOT/skills/solar-interface/scripts/client_lib.sh"

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

assert_eq() {
  local label="$1"
  local got="$2"
  local want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label (got=$got want=$want)" >&2
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

INSTALL="$TMP/install"
WS="$TMP/workspace"
mkdir -p "$INSTALL/core/skills/solar-interface/scripts" "$WS/sun" "$WS/.solar"
cp -R "$CORE_ROOT/skills/solar-interface" "$INSTALL/core/skills/"
cp -R "$CORE_ROOT/scripts" "$INSTALL/core/scripts"

solar_client_write_manifest_v11 "$WS" "$INSTALL"

assert_eq "core_source default global" "$(solar_client_manifest_core_source "$WS/.solar/manifest.json")" "global"
assert_eq "requires_global_client default" "$(solar_client_manifest_field "$WS/.solar/manifest.json" requires_global_client)" "true"

if python3 - <<'PY' "$WS/.solar/manifest.json"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
assert data.get("portable_capabilities") == []
PY
then
  assert_ok "portable_capabilities empty list" true
else
  assert_ok "portable_capabilities empty list" false
fi

solar_client_write_manifest_portable "$WS" "abc123" "solar-interface,solar-router"
assert_eq "portable core_source" "$(solar_client_manifest_core_source "$WS/.solar/manifest.json")" "workspace-snapshot"
assert_eq "portable requires_global false" "$(solar_client_manifest_field "$WS/.solar/manifest.json" requires_global_client)" "false"

solar_client_bump_manifest_from_install "$WS" "$INSTALL"
assert_eq "bump preserves workspace-snapshot" "$(solar_client_manifest_core_source "$WS/.solar/manifest.json")" "workspace-snapshot"

WS2="$TMP/workspace2"
mkdir -p "$WS2/sun" "$WS2/.solar"
solar_client_write_manifest_v11 "$WS2" "$INSTALL"
solar_client_bump_manifest_from_install "$WS2" "$INSTALL"
assert_eq "bump sets global on fresh ws" "$(solar_client_manifest_core_source "$WS2/.solar/manifest.json")" "global"

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
