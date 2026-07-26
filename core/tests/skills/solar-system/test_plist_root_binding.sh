#!/usr/bin/env bash
# Unit tests for LaunchAgent SOLAR_ROOT binding helpers (solar-system).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_LIB="$(cd "$SCRIPT_DIR/../../../skills/solar-system/scripts" && pwd)/system_lib.sh"
# shellcheck source=/dev/null
source "$SYSTEM_LIB"

PASS=0
FAIL=0

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
    return 0
  fi
  echo "FAIL: $label (expected='$expected' actual='$actual')" >&2
  FAIL=$((FAIL + 1))
  return 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

GOOD_ROOT="$TMP/good-install"
BAD_ROOT="$TMP/missing-install"
OTHER_ROOT="$TMP/other-install"
mkdir -p \
  "$GOOD_ROOT/core/skills/solar-system/scripts" \
  "$GOOD_ROOT/core/skills/solar-router/scripts" \
  "$OTHER_ROOT/core/skills/solar-system/scripts" \
  "$OTHER_ROOT/core/skills/solar-router/scripts"
touch \
  "$GOOD_ROOT/core/skills/solar-system/scripts/run_orchestrator.sh" \
  "$GOOD_ROOT/core/skills/solar-router/scripts/run_router.py" \
  "$OTHER_ROOT/core/skills/solar-system/scripts/run_orchestrator.sh" \
  "$OTHER_ROOT/core/skills/solar-router/scripts/run_router.py"

INCOMPLETE="$TMP/incomplete-install"
mkdir -p "$INCOMPLETE/core/skills/solar-system/scripts"
touch "$INCOMPLETE/core/skills/solar-system/scripts/run_orchestrator.sh"

NO_ORCH="$TMP/no-orch-install"
mkdir -p "$NO_ORCH/core/skills/solar-router/scripts"
touch "$NO_ORCH/core/skills/solar-router/scripts/run_router.py"

assert_eq "empty root → missing_key" \
  "missing_key" "$(solar_system_classify_plist_root "" "$GOOD_ROOT")"

assert_eq "missing directory → root_missing" \
  "root_missing" "$(solar_system_classify_plist_root "$BAD_ROOT" "$GOOD_ROOT")"

assert_eq "router without orchestrator → orchestrator_missing" \
  "orchestrator_missing" "$(solar_system_classify_plist_root "$NO_ORCH" "$GOOD_ROOT")"

assert_eq "orchestrator without router → router_missing" \
  "router_missing" "$(solar_system_classify_plist_root "$INCOMPLETE" "$GOOD_ROOT")"

assert_eq "valid match → ok" \
  "ok" "$(solar_system_classify_plist_root "$GOOD_ROOT" "$GOOD_ROOT")"

assert_eq "valid but different install → mismatch" \
  "mismatch" "$(solar_system_classify_plist_root "$OTHER_ROOT" "$GOOD_ROOT")"

assert_eq "trailing slash still ok" \
  "ok" "$(solar_system_classify_plist_root "$GOOD_ROOT/" "$GOOD_ROOT")"

# Severity mapping used by check_orchestrator (stale → DOWN, never silent HEALTHY).
for status in missing_key root_missing orchestrator_missing router_missing mismatch; do
  assert_eq "severity($status) → DOWN" \
    "DOWN" "$(solar_system_plist_root_severity "$status")"
done
assert_eq "severity(ok) → HEALTHY" "HEALTHY" "$(solar_system_plist_root_severity "ok")"
assert_eq "severity(skipped) → HEALTHY" "HEALTHY" "$(solar_system_plist_root_severity "skipped")"

# Darwin: PlistBuddy read of EnvironmentVariables.SOLAR_ROOT
if [[ "$(uname -s)" == "Darwin" ]] && [[ -x /usr/libexec/PlistBuddy ]]; then
  PLIST_OK="$TMP/ok.plist"
  PLIST_NO_KEY="$TMP/nokey.plist"
  cat >"$PLIST_OK" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SOLAR_ROOT</key>
    <string>$GOOD_ROOT</string>
    <key>SOLAR_WORKSPACE</key>
    <string>$TMP/ws</string>
  </dict>
</dict>
</plist>
EOF
  cat >"$PLIST_NO_KEY" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SOLAR_WORKSPACE</key>
    <string>/tmp/ws</string>
  </dict>
</dict>
</plist>
EOF
  assert_eq "PlistBuddy reads SOLAR_ROOT" \
    "$GOOD_ROOT" "$(solar_system_plist_solar_root "$PLIST_OK")"
  # Missing key → empty string (caller treats as missing_key)
  got="$(solar_system_plist_solar_root "$PLIST_NO_KEY")"
  assert_eq "PlistBuddy missing SOLAR_ROOT → empty" "" "$got"
  assert_eq "classify after empty PlistBuddy read → missing_key" \
    "missing_key" "$(solar_system_classify_plist_root "$got" "$GOOD_ROOT")"
  assert_eq "end-to-end: plist root + classify → ok" \
    "ok" "$(solar_system_classify_plist_root "$(solar_system_plist_solar_root "$PLIST_OK")" "$GOOD_ROOT")"
  assert_eq "end-to-end stale path in plist → root_missing" \
    "root_missing" "$(solar_system_classify_plist_root "$(solar_system_plist_solar_root "$PLIST_OK" | sed "s|$GOOD_ROOT|$BAD_ROOT|")" "$GOOD_ROOT")"
  # Binary plist round-trip
  PLIST_BIN="$TMP/ok.binary.plist"
  plutil -convert binary1 -o "$PLIST_BIN" "$PLIST_OK"
  assert_eq "PlistBuddy reads binary plist SOLAR_ROOT" \
    "$GOOD_ROOT" "$(solar_system_plist_solar_root "$PLIST_BIN")"
else
  echo "SKIP: Darwin PlistBuddy tests (not on macOS)"
fi

echo ""
echo "Passed: $PASS  Failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
