#!/usr/bin/env bash
# Unit tests for solar client update helpers (Fase 2).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
UPDATE_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/client_update.sh"
# shellcheck source=client_lib.sh
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
assert_ok "check report mentions SOLAR_ROOT" grep -q 'SOLAR_ROOT' <<< "$report"

# --- bundle backup core only ---
INSTALL3="$TMP/install-bundle"
mkdir -p "$INSTALL3/core"
echo "probe" > "$INSTALL3/core/.bundle-probe"
backup_path="$(solar_client_backup_install_core "$INSTALL3" "v0.0-test")"
assert_ok "bundle backup creates core subtree" test -d "$backup_path/core"
assert_ok "bundle backup preserves probe" test -f "$backup_path/core/.bundle-probe"

# --- git install backup includes .git/objects (restorable snapshot) ---
INSTALL5="$TMP/install-git-backup"
mkdir -p "$INSTALL5/core"
git -C "$INSTALL5" init -q
git -C "$INSTALL5" config user.email "test@test"
git -C "$INSTALL5" config user.name "Test"
echo "git-backup-probe" > "$INSTALL5/core/.git-backup-probe"
git -C "$INSTALL5" add -A && git -C "$INSTALL5" commit -q -m "init"
git_backup_path="$(solar_client_backup_install_git "$INSTALL5" "v0.0-git")"
assert_ok "git backup includes .git/objects dir" test -d "$git_backup_path/.git/objects"
object_files="$(find "$git_backup_path/.git/objects" -type f 2>/dev/null | wc -l | tr -d ' ')"
assert_ok "git backup copies object store" test "${object_files:-0}" -gt 0

# --- client_update.sh: --tag without value ---
set +e
tag_err="$(bash "$UPDATE_SCRIPT" --tag 2>&1)"
tag_ec=$?
set -e
assert_ok "update --tag without value exits 2" test "$tag_ec" -eq 2
assert_ok "update --tag without value error message" grep -q 'ERROR: --tag requires a value' <<< "$tag_err"

# --- rotate backups (keep newest by mtime) ---
for i in 1 2 3 4 5 6; do
  mkdir -p "$INSTALL3/backups/backup-$i"
  touch -t "2026010${i}1200" "$INSTALL3/backups/backup-$i"
done
solar_client_rotate_backups "$INSTALL3" 3 >/dev/null
remaining="$(find "$INSTALL3/backups" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
assert_ok "rotate keeps at most 3 backups" test "${remaining:-0}" -le 3
assert_ok "rotate drops oldest backup-1" test ! -d "$INSTALL3/backups/backup-1"
assert_ok "rotate keeps newest backup-6" test -d "$INSTALL3/backups/backup-6"

# --- manifest bump includes core_commit ---
WS2="$TMP/ws-sync"
INSTALL4="$TMP/install-sync"
mkdir -p "$WS2/.solar" "$WS2/sun" "$INSTALL4/core"
printf '%s\n' '{"layout":"solar-client-v1.1","core_version":"v0.0.0","core_commit":"deadbeef","core_source":"global"}' > "$WS2/.solar/manifest.json"
git -C "$INSTALL4" init -q
git -C "$INSTALL4" config user.email "test@test"
git -C "$INSTALL4" config user.name "Test"
echo "y" > "$INSTALL4/core/.probe"
git -C "$INSTALL4" add -A && git -C "$INSTALL4" commit -q -m "init"
solar_client_bump_manifest_from_install "$WS2" "$INSTALL4"
head_commit="$(git -C "$INSTALL4" rev-parse HEAD)"
manifest_commit="$(solar_client_manifest_core_commit "$WS2/.solar/manifest.json")"
assert_ok "bump_manifest sets core_commit to SOLAR_ROOT HEAD" test "$manifest_commit" = "$head_commit"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
