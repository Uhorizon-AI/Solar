#!/usr/bin/env bash
# E2E / acceptance tests for Solar Client install (isolated TMP).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
FRAMEWORK_ROOT="$(cd "$CORE_ROOT/.." && pwd)"
INSTALL_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/install_solar_client.sh"
UNINSTALL_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/uninstall_solar_client.sh"
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

assert_fail() {
  local label="$1"
  shift
  set +e
  "$@" >/dev/null 2>&1
  local ec=$?
  set -e
  if [[ "$ec" -ne 0 ]]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label (expected failure)" >&2
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- unit: resolve via fixture file:// API ---
FIXTURE="$TMP/latest.json"
cat > "$FIXTURE" <<'JSON'
{
  "tag_name": "v9.9.9",
  "draft": false,
  "prerelease": false
}
JSON
export SOLAR_RELEASES_API_URL="file://${FIXTURE}"
unset SOLAR_STABLE_RELEASE_TAG || true
got="$(solar_client_resolve_stable_release_tag)"
assert_ok "resolve_stable_release_tag from fixture" test "$got" = "v9.9.9"

export SOLAR_STABLE_RELEASE_TAG="v1.2.3"
got="$(solar_client_resolve_stable_release_tag)"
assert_ok "SOLAR_STABLE_RELEASE_TAG override" test "$got" = "v1.2.3"
unset SOLAR_STABLE_RELEASE_TAG

PRERELEASE="$TMP/pre.json"
cat > "$PRERELEASE" <<'JSON'
{"tag_name":"v9.9.9-beta.1","draft":false,"prerelease":true}
JSON
export SOLAR_RELEASES_API_URL="file://${PRERELEASE}"
assert_fail "reject prerelease latest" solar_client_resolve_stable_release_tag >/dev/null

# --- prepare local clone source (current framework tree as git remote) ---
# Use the live framework git root so refs exist.
assert_ok "framework is git repo" git -C "$FRAMEWORK_ROOT" rev-parse --is-inside-work-tree >/dev/null

REF="$(git -C "$FRAMEWORK_ROOT" rev-parse HEAD)"
INSTALL_DIR="$TMP/install"
BIN_DIR="$TMP/bin"
WS="$TMP/workspace"
mkdir -p "$BIN_DIR" "$WS"

# Track files outside TMP (should remain empty of new solar wrappers)
OUTSIDE_PROBE="$TMP/../outside-should-not-exist-$$"
rm -f "$OUTSIDE_PROBE" 2>/dev/null || true

export SOLAR_REPO_URL="$FRAMEWORK_ROOT"
export SOLAR_BIN_DIR="$BIN_DIR"
unset SOLAR_ROOT || true

# Install with explicit --ref (CI must not depend on production releases/latest)
set +e
out="$(bash "$INSTALL_SCRIPT" --install-dir "$INSTALL_DIR" --ref "$REF" --yes 2>&1)"
ec=$?
set -e
echo "$out"
assert_ok "install exits 0" test "$ec" -eq 0
assert_ok "wrapper exists" test -x "$BIN_DIR/solar"

# Smoke MUST invoke wrapper directly (never via bash) to catch mode 100644
set +e
ver_out="$("$BIN_DIR/solar" --version 2>&1)"
ver_ec=$?
set -e
assert_ok "wrapper --version exit 0" test "$ver_ec" -eq 0
assert_ok "wrapper --version prints solar" grep -q 'solar' <<<"$ver_out"

# Idempotent second install
set +e
out2="$(bash "$INSTALL_SCRIPT" --install-dir "$INSTALL_DIR" --ref "$REF" --yes 2>&1)"
ec2=$?
set -e
assert_ok "second install exits 0" test "$ec2" -eq 0

# Existing installs with local changes must never be overwritten.
printf '\nlocal-test-change\n' >> "$INSTALL_DIR/README.md"
set +e
dirty_out="$(bash "$INSTALL_SCRIPT" --install-dir "$INSTALL_DIR" --ref "$REF" --yes 2>&1)"
dirty_ec=$?
set -e
assert_ok "dirty install is rejected" test "$dirty_ec" -ne 0
assert_ok "dirty install reports local modifications" grep -q 'local modifications' <<<"$dirty_out"
assert_ok "dirty install preserves local change" grep -q 'local-test-change' "$INSTALL_DIR/README.md"
git -C "$INSTALL_DIR" checkout -- README.md

# Destructive uninstall must validate the install before removing anything.
NOT_INSTALL="$TMP/not-a-solar-install"
GUARD_BIN="$TMP/guard-bin"
mkdir -p "$NOT_INSTALL" "$GUARD_BIN"
printf 'keep\n' > "$NOT_INSTALL/data.txt"
printf '#!/usr/bin/env bash\n' > "$GUARD_BIN/solar"
chmod +x "$GUARD_BIN/solar"
set +e
guard_out="$(SOLAR_ROOT="$NOT_INSTALL" SOLAR_BIN_DIR="$GUARD_BIN" \
  bash "$UNINSTALL_SCRIPT" --remove-install --yes 2>&1)"
guard_ec=$?
set -e
assert_ok "uninstall rejects unmanaged install path" test "$guard_ec" -ne 0
assert_ok "uninstall preserves unmanaged directory" test -f "$NOT_INSTALL/data.txt"
assert_ok "uninstall preserves wrapper when validation fails" test -f "$GUARD_BIN/solar"

# Workspace init/sync/doctor via absolute wrapper
export SOLAR_ROOT="$INSTALL_DIR"
cd "$WS"
set +e
init_out="$("$BIN_DIR/solar" client init 2>&1)"
init_ec=$?
sync_out="$("$BIN_DIR/solar" client sync 2>&1)"
sync_ec=$?
doc_out="$("$BIN_DIR/solar" client doctor --strict 2>&1)"
doc_ec=$?
ws_doc_out="$("$BIN_DIR/solar" workspace doctor 2>&1)"
ws_doc_ec=$?
set -e

echo "init: $init_ec"
echo "sync: $sync_ec"
echo "doctor: $doc_ec"
echo "workspace doctor: $ws_doc_ec"

assert_ok "client init exit 0" test "$init_ec" -eq 0
assert_ok "client sync exit 0" test "$sync_ec" -eq 0
assert_ok "client doctor --strict exit 0" test "$doc_ec" -eq 0
assert_ok "workspace doctor exit 0" test "$ws_doc_ec" -eq 0

# Ensure install did not create wrapper outside BIN_DIR
assert_ok "no stray outside probe" test ! -e "$OUTSIDE_PROBE"

# --ref without value
set +e
bash "$INSTALL_SCRIPT" --install-dir "$TMP/x" --ref 2>"$TMP/err.txt"
ec_ref=$?
set -e
assert_ok "--ref without value exits 2" test "$ec_ref" -eq 2

# Bootstrap must accept a commit SHA (not only branch/tag tips).
# Use a throwaway repo that includes the current working-tree installer (HEAD may
# predate --ref support while this change is still uncommitted).
BOOTSTRAP_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/bootstrap_solar_client.sh"
BOOT_SRC="$TMP/boot-src"
BOOT_INSTALL="$TMP/boot-sha-install"
BOOT_BIN="$TMP/boot-sha-bin"
mkdir -p "$BOOT_BIN"
git -c core.hooksPath=/dev/null clone --local "$FRAMEWORK_ROOT" "$BOOT_SRC" >/dev/null 2>&1
cp "$INSTALL_SCRIPT" "$BOOT_SRC/core/skills/solar-client/scripts/install_solar_client.sh"
cp "$BOOTSTRAP_SCRIPT" "$BOOT_SRC/core/skills/solar-client/scripts/bootstrap_solar_client.sh"
cp "$CORE_ROOT/skills/solar-client/scripts/client_lib.sh" \
  "$BOOT_SRC/core/skills/solar-client/scripts/client_lib.sh"
cp "$CORE_ROOT/skills/solar-client/scripts/solar" \
  "$BOOT_SRC/core/skills/solar-client/scripts/solar"
chmod +x \
  "$BOOT_SRC/core/skills/solar-client/scripts/install_solar_client.sh" \
  "$BOOT_SRC/core/skills/solar-client/scripts/bootstrap_solar_client.sh" \
  "$BOOT_SRC/core/skills/solar-client/scripts/solar"
git -C "$BOOT_SRC" config user.email "test@test"
git -C "$BOOT_SRC" config user.name "Test"
git -C "$BOOT_SRC" add -A
git -C "$BOOT_SRC" commit -q -m "test: installer with --ref"
BOOT_SHA="$(git -C "$BOOT_SRC" rev-parse HEAD)"
unset SOLAR_BOOTSTRAP_FROM_LOCAL || true
set +e
boot_out="$(
  SOLAR_REPO_URL="$BOOT_SRC" SOLAR_BIN_DIR="$BOOT_BIN" \
    bash "$BOOTSTRAP_SCRIPT" --install-dir "$BOOT_INSTALL" --ref "$BOOT_SHA" --yes 2>&1
)"
boot_ec=$?
set -e
echo "$boot_out" | tail -20
assert_ok "bootstrap with commit SHA exits 0" test "$boot_ec" -eq 0
assert_ok "bootstrap SHA used fallback clone path" grep -q 'shallow --branch' <<<"$boot_out"
assert_ok "bootstrap SHA wrapper works" test -x "$BOOT_BIN/solar"
set +e
boot_ver_ec=0
"$BOOT_BIN/solar" --version >/dev/null 2>&1 || boot_ver_ec=$?
set -e
assert_ok "bootstrap SHA wrapper --version" test "$boot_ver_ec" -eq 0

echo ""
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
