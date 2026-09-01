#!/usr/bin/env bash
# Unit tests for manifest dual-mode contract (Fase 3A).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# shellcheck source=/dev/null
source "$CORE_ROOT/skills/solar-client/scripts/client_lib.sh"

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
mkdir -p "$INSTALL/core/skills/solar-app/scripts" "$WS/sun" "$WS/.solar"
cp -R "$CORE_ROOT/skills/solar-app" "$INSTALL/core/skills/"
cp -R "$CORE_ROOT/scripts" "$INSTALL/core/scripts"

solar_client_write_settings_v12 "$WS" "$INSTALL"
SETTINGS="$(solar_client_settings_path "$WS")"

assert_eq "writes settings.json" "$(basename "$SETTINGS")" "settings.json"
assert_eq "core_source default global" "$(solar_client_manifest_core_source "$SETTINGS")" "global"
assert_eq "requires_global_client default" "$(solar_client_manifest_field "$SETTINGS" requires_global_client)" "true"
assert_eq "layout v1.2" "$(solar_client_manifest_field "$SETTINGS" layout)" "solar-client-v1.2"

if python3 - <<PY "$SETTINGS"
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
assert data.get("portable_capabilities") == []
assert data.get("scope") == "workspace"
PY
then
  assert_ok "portable_capabilities empty list" true
else
  assert_ok "portable_capabilities empty list" false
fi

solar_client_write_manifest_portable "$WS" "abc123" "solar-app,solar-router"
SETTINGS="$(solar_client_settings_path "$WS")"
assert_eq "portable core_source" "$(solar_client_manifest_core_source "$SETTINGS")" "workspace-snapshot"
assert_eq "portable requires_global false" "$(solar_client_manifest_field "$SETTINGS" requires_global_client)" "false"

solar_client_bump_manifest_from_install "$WS" "$INSTALL"
SETTINGS="$(solar_client_settings_path "$WS")"
assert_eq "bump preserves workspace-snapshot" "$(solar_client_manifest_core_source "$SETTINGS")" "workspace-snapshot"

WS2="$TMP/workspace2"
mkdir -p "$WS2/sun" "$WS2/.solar"
solar_client_write_settings_v12 "$WS2" "$INSTALL"
solar_client_bump_manifest_from_install "$WS2" "$INSTALL"
SETTINGS2="$(solar_client_settings_path "$WS2")"
assert_eq "bump sets global on fresh ws" "$(solar_client_manifest_core_source "$SETTINGS2")" "global"

WS3="$TMP/workspace3"
mkdir -p "$WS3/sun" "$WS3/.solar"
printf '%s\n' '{"layout":"solar-client-v1.1","core_version":"old","core_source":"workspace-snapshot","snapshot_outdated":false}' \
  >"$WS3/.solar/manifest.json"
solar_client_mark_snapshot_outdated "$WS3" true
SETTINGS3="$(solar_client_settings_path "$WS3")"
assert_eq "snapshot marker migrates layout" "$(solar_client_manifest_field "$SETTINGS3" layout)" "solar-client-v1.2"
assert_eq "snapshot marker forces workspace scope" "$(solar_client_manifest_field "$SETTINGS3" scope)" "workspace"
assert_eq "snapshot marker writes requested value" "$(solar_client_manifest_field "$SETTINGS3" snapshot_outdated)" "true"
assert_ok "snapshot marker removes legacy manifest" test ! -f "$WS3/.solar/manifest.json"

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
