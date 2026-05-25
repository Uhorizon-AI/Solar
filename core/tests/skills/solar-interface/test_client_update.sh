#!/usr/bin/env bash
# Unit tests for solar client update helpers (Fase 2).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# shellcheck source=client_lib.sh
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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- manifest repair helpers ---
WS="$TMP/ws-repair"
INSTALL="$TMP/install-repair"
mkdir -p "$WS/.solar" "$WS/sun" "$INSTALL/core"
printf '%s\n' '<<<<<<< HEAD' '{"layout":"broken"}' > "$WS/.solar/manifest.json"
assert_ok "needs_repair detects conflict markers" solar_client_manifest_needs_repair "$WS/.solar/manifest.json"
solar_client_repair_manifest "$WS" "$INSTALL"
assert_ok "repair: valid layout" grep -q 'solar-client-v1.1' "$WS/.solar/manifest.json"
if ! grep -q '<<<<<<<' "$WS/.solar/manifest.json" 2>/dev/null; then
  echo "PASS: repair: no conflict markers"
  PASS=$((PASS + 1))
else
  echo "FAIL: repair: no conflict markers" >&2
  FAIL=$((FAIL + 1))
fi

# --- update check report ---
INSTALL2="$TMP/install-check"
mkdir -p "$INSTALL2/core" "$WS/sun"
git -C "$INSTALL2" init -q
git -C "$INSTALL2" config user.email "test@test"
git -C "$INSTALL2" config user.name "Test"
echo "x" > "$INSTALL2/README"
git -C "$INSTALL2" add README && git -C "$INSTALL2" commit -q -m "init"
report="$(solar_client_update_check_report "$INSTALL2" "$WS")"
assert_ok "check report mentions SOLAR_ROOT" echo "$report" | grep -q 'SOLAR_ROOT'

# --- bundle backup core only ---
INSTALL3="$TMP/install-bundle"
mkdir -p "$INSTALL3/core"
echo "probe" > "$INSTALL3/core/.bundle-probe"
backup_path="$(solar_client_backup_install_core "$INSTALL3" "v0.0-test")"
assert_ok "bundle backup creates core subtree" test -d "$backup_path/core"
assert_ok "bundle backup preserves probe" test -f "$backup_path/core/.bundle-probe"

# --- rotate backups ---
for i in 1 2 3 4 5 6; do
  mkdir -p "$INSTALL3/backups/backup-$i"
done
solar_client_rotate_backups "$INSTALL3" 3 >/dev/null
remaining="$(find "$INSTALL3/backups" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
assert_ok "rotate keeps at most 3 backups" test "${remaining:-0}" -le 3

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
