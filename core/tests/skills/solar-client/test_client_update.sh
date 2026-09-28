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

# Nothing in this file may claim the machine runtime or call system launchctl.
# shellcheck source=../../../../tests/support/shell_runtime_guard.sh
source "$CORE_ROOT/tests/support/shell_runtime_guard.sh"
mkdir -p "$TMP/guard-bin" "$TMP/guard-runtime"
cat >"$TMP/guard-bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/guard-bin/launchctl"
export PATH="$TMP/guard-bin:${PATH}"
export SOLAR_APP_DATA="$TMP/guard-app"
export SOLAR_RUNTIME_ROOT="$TMP/guard-runtime"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl"
solar_test_guard

# --- manifest repair helpers ---
WS="$TMP/ws-repair"
INSTALL="$TMP/install-repair"
mkdir -p "$WS/.solar" "$WS/sun" "$INSTALL/core"
printf '%s\n' '<<<<<<< HEAD' '{"layout":"broken"}' > "$WS/.solar/manifest.json"
assert_ok "needs_repair detects conflict markers" solar_client_manifest_needs_repair "$WS/.solar/manifest.json"
solar_client_repair_manifest "$WS" "$INSTALL"
assert_ok "repair: valid layout" grep -q 'solar-client-v1.2' "$WS/.solar/settings.json"
if ! grep -q '<<<<<<<' "$WS/.solar/settings.json" 2>/dev/null; then
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

# --- nested workspace: backups under workspace root, not under solar/ ---
NEST_WS="$TMP/nest-ws"
NEST_INSTALL="$NEST_WS/solar"
mkdir -p "$NEST_INSTALL/core"
NEST_WS="$(cd "$NEST_WS" && pwd -P)"
NEST_INSTALL="$(cd "$NEST_INSTALL" && pwd -P)"
echo "nested" > "$NEST_INSTALL/core/.nested-probe"
nested_dir="$(solar_client_backups_dir "$NEST_INSTALL" "$NEST_WS")"
assert_ok "nested backups dir is workspace/backups" test "$nested_dir" = "$NEST_WS/backups"
nested_backup="$(solar_client_backup_install_core "$NEST_INSTALL" "v0.0-nested" "$NEST_WS")"
assert_ok "nested backup under workspace/backups" test "${nested_backup#"$NEST_WS/backups/"}" != "$nested_backup"
assert_ok "nested backup preserves probe" test -f "$nested_backup/core/.nested-probe"
assert_ok "no backup under install root" test ! -d "$NEST_INSTALL/backups"

# --- bundle backup core only ---
INSTALL3="$TMP/install-bundle"
mkdir -p "$INSTALL3/core"
echo "probe" > "$INSTALL3/core/.bundle-probe"
backup_path="$(solar_client_backup_install_core "$INSTALL3" "v0.0-test")"
assert_ok "bundle backup creates core subtree" test -d "$backup_path/core"
assert_ok "bundle backup preserves probe" test -f "$backup_path/core/.bundle-probe"

# --- Fase 2.1: skip rsync backup on clean git unless --backup ---
INSTALL_GIT_CLEAN="$TMP/install-git-clean"
mkdir -p "$INSTALL_GIT_CLEAN/core"
git -C "$INSTALL_GIT_CLEAN" init -q
git -C "$INSTALL_GIT_CLEAN" config user.email "test@test"
git -C "$INSTALL_GIT_CLEAN" config user.name "Test"
echo "clean" > "$INSTALL_GIT_CLEAN/README"
git -C "$INSTALL_GIT_CLEAN" add README && git -C "$INSTALL_GIT_CLEAN" commit -q -m "init"
set +e
solar_client_should_rsync_backup_git "$INSTALL_GIT_CLEAN" false
ec_clean=$?
solar_client_should_rsync_backup_git "$INSTALL_GIT_CLEAN" true
ec_force=$?
set -e
assert_ok "git mode skips backup unless --backup (clean)" test "$ec_clean" -ne 0
assert_ok "git mode backs up with --backup" test "$ec_force" -eq 0
echo "dirty" >> "$INSTALL_GIT_CLEAN/README"
set +e
solar_client_should_rsync_backup_git "$INSTALL_GIT_CLEAN" false
ec_dirty=$?
set -e
assert_ok "git mode skips backup unless --backup (dirty)" test "$ec_dirty" -ne 0

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
manifest_commit="$(solar_client_manifest_core_commit "$(solar_client_settings_path "$WS2")")"
assert_ok "bump_manifest sets core_commit to SOLAR_ROOT HEAD" test "$manifest_commit" = "$head_commit"
assert_ok "bump migrates to settings.json" test -f "$WS2/.solar/settings.json"
assert_ok "bump removes legacy manifest" test ! -f "$WS2/.solar/manifest.json"

# --- integration: migration failure aborts BEFORE framework update (§B) ---
WS_MIG="$TMP/ws-mig-fail"
INSTALL_MIG="$WS_MIG/solar"
mkdir -p "$WS_MIG/sun" "$INSTALL_MIG/core/skills/solar-client/scripts"
printf '%s\n' '# test core' > "$INSTALL_MIG/core/AGENTS.md"
printf '%s\n' '#!/usr/bin/env bash' 'echo solar-stub' > "$INSTALL_MIG/core/skills/solar-client/scripts/solar"
chmod +x "$INSTALL_MIG/core/skills/solar-client/scripts/solar"
printf '%s\n' 'OLD' > "$INSTALL_MIG/core/.version-marker"
# Second commit we would move to if update applied — stay unreachable on migrate fail
git -C "$INSTALL_MIG" init -q
git -C "$INSTALL_MIG" config user.email "test@test"
git -C "$INSTALL_MIG" config user.name "Test"
git -C "$INSTALL_MIG" add -A && git -C "$INSTALL_MIG" commit -q -m "old-core"
printf '%s\n' 'NEW' > "$INSTALL_MIG/core/.version-marker"
git -C "$INSTALL_MIG" add -A && git -C "$INSTALL_MIG" commit -q -m "new-core"
git -C "$INSTALL_MIG" checkout -q HEAD~1
assert_ok "fixture core marker is OLD before update" grep -qx 'OLD' "$INSTALL_MIG/core/.version-marker"

cat >"$WS_MIG/.env" <<'EOF'
SOLAR_ROUTER_PROVIDER_PRIORITY=gemini,codex
EOF
mkdir -p "$WS_MIG/.solar" "$TMP/mig-runtime"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"v0.0.1","core_commit":"unknown","core_source":"global","workspace_id":"mig-workspace"}' \
  >"$WS_MIG/.solar/settings.json"
# Directory not writable → atomic .env rewrite fails; update must abort pre-apply
chmod a-w "$WS_MIG"
set +e
mig_out="$(SOLAR_RUNTIME_ROOT="$TMP/mig-runtime" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  bash "$UPDATE_SCRIPT" --workspace "$WS_MIG" --yes 2>&1)"
mig_ec=$?
set -e
chmod u+w "$WS_MIG" 2>/dev/null || true
assert_ok "update exits non-zero when .env migration fails" test "$mig_ec" -ne 0
assert_ok "update says abort before framework update" grep -qi 'aborting before framework update' <<< "$mig_out"
assert_ok "core marker unchanged (OLD) after failed migration" grep -qx 'OLD' "$INSTALL_MIG/core/.version-marker"
assert_ok "legacy gemini priority still present after failed migration" grep -Eq 'PRIORITY=gemini' "$WS_MIG/.env"

# --- LaunchAgent assess helpers (Darwin / no-system-lib) ---
EMPTY_INSTALL="$TMP/empty-install"
mkdir -p "$EMPTY_INSTALL/core"
if [[ "$(uname -s)" == "Darwin" ]]; then
  assert_ok "assess missing system_lib → no_system_lib" \
    test "$(solar_client_assess_launchagent "$EMPTY_INSTALL")" = "no_system_lib"
  # Real tree in this repo should classify against live plist without crashing.
  live_status="$(solar_client_assess_launchagent "$CORE_ROOT/..")"
  case "$live_status" in
    ok|absent|missing_key|root_missing|orchestrator_missing|router_missing|mismatch|no_system_lib)
      echo "PASS: assess live install status=$live_status"
      PASS=$((PASS + 1))
      ;;
    *)
      echo "FAIL: unexpected assess status=$live_status" >&2
      FAIL=$((FAIL + 1))
      ;;
  esac
  report_out="$(solar_client_report_launchagent_binding "$EMPTY_INSTALL" false 2>&1)"
  assert_ok "report mentions skipped/missing helpers" \
    grep -Eqi 'LaunchAgent: skipped|solar-system helpers missing' <<< "$report_out"
else
  assert_ok "assess non-Darwin → skipped_os" \
    test "$(solar_client_assess_launchagent "$EMPTY_INSTALL")" = "skipped_os"
fi

# usage documents the new flag
assert_ok "usage lists --reinstall-launchagent" \
  grep -q -- '--reinstall-launchagent' <<<"$(bash "$UPDATE_SCRIPT" -h 2>&1)"
assert_ok "usage says --check is incompatible with reinstall" \
  grep -Eqi 'Incompatible with --check|read-only' <<<"$(bash "$UPDATE_SCRIPT" -h 2>&1)"

# --check --reinstall-launchagent must fail before any mutation
CHECK_WS="$TMP/check-ro-ws"
mkdir -p "$CHECK_WS/sun" "$CHECK_WS/.solar"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"v0.20.2","core_source":"global"}' \
  >"$CHECK_WS/.solar/settings.json"
MARKER_CHECK="$TMP/must-not-touch"
rm -f "$MARKER_CHECK"
export SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=mismatch
export SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT="$TMP/must-not-run-install.sh"
cat >"$SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT" <<EOF
#!/usr/bin/env bash
echo touched >"$MARKER_CHECK"
exit 0
EOF
chmod +x "$SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT"
set +e
combo_out="$(bash "$UPDATE_SCRIPT" --workspace "$CHECK_WS" --check --reinstall-launchagent 2>&1)"
combo_ec=$?
set -e
assert_ok "--check --reinstall-launchagent exits 2" test "$combo_ec" -eq 2
assert_ok "--check --reinstall-launchagent error mentions read-only" \
  grep -Eqi 'read-only|do not combine' <<< "$combo_out"
assert_ok "--check --reinstall-launchagent did not run install script" \
  test ! -f "$MARKER_CHECK"
unset SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE
unset SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT

# Isolated reinstall flow with mocked install + gateway scripts
MOCK_INSTALL_ROOT="$TMP/mock-install"
mkdir -p "$MOCK_INSTALL_ROOT/core"
FAKE_INSTALL="$TMP/fake-install-launchagent.sh"
FAKE_SETUP="$TMP/fake-setup-gateway.sh"
INSTALL_MARK="$TMP/install-ran"
SETUP_MARK="$TMP/setup-ran"
cat >"$FAKE_INSTALL" <<EOF
#!/usr/bin/env bash
echo ok >"$INSTALL_MARK"
exit 0
EOF
cat >"$FAKE_SETUP" <<EOF
#!/usr/bin/env bash
echo ok >"$SETUP_MARK"
exit 0
EOF
chmod +x "$FAKE_INSTALL" "$FAKE_SETUP"
export SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=mismatch
export SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT="$FAKE_INSTALL"
export SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT="$FAKE_SETUP"
set +e
re_out="$(solar_client_report_launchagent_binding "$MOCK_INSTALL_ROOT" true 2>&1)"
re_ec=$?
set -e
assert_ok "mocked reinstall exits 0" test "$re_ec" -eq 0
assert_ok "mocked reinstall ran install script" test -f "$INSTALL_MARK"
assert_ok "mocked reinstall ran gateway setup" test -f "$SETUP_MARK"
assert_ok "mocked reinstall reports OK" grep -q 'OK: LaunchAgent SOLAR_ROOT matches install' <<< "$re_out"
unset SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE
unset SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT
unset SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT

# Gateway restart failure → non-zero (LaunchAgent install may have run)
FAIL_SETUP="$TMP/fake-setup-fail.sh"
INSTALL_MARK2="$TMP/install-ran-2"
cat >"$FAKE_INSTALL" <<EOF
#!/usr/bin/env bash
echo ok >"$INSTALL_MARK2"
exit 0
EOF
cat >"$FAIL_SETUP" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$FAKE_INSTALL" "$FAIL_SETUP"
export SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=root_missing
export SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT="$FAKE_INSTALL"
export SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT="$FAIL_SETUP"
set +e
fail_out="$(solar_client_report_launchagent_binding "$MOCK_INSTALL_ROOT" true 2>&1)"
fail_ec=$?
set -e
assert_ok "gateway fail after reinstall exits non-zero" test "$fail_ec" -ne 0
assert_ok "gateway fail still ran install script" test -f "$INSTALL_MARK2"
assert_ok "gateway fail error is explicit" \
  grep -Eqi 'gateway restart failed|transport gateway restart failed' <<< "$fail_out"
unset SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE
unset SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT
unset SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT

# --- restart running services after update ---
SVC_LOG="$TMP/services.log"
FAKE_SVC_SETUP="$TMP/svc-setup.sh"
FAKE_HOST_STOP="$TMP/host-stop.sh"
FAKE_HOST_START="$TMP/host-start.sh"
printf '#!/usr/bin/env bash\necho "gateway $*" >>"%s"\n' "$SVC_LOG" >"$FAKE_SVC_SETUP"
printf '#!/usr/bin/env bash\necho host-stop >>"%s"\n' "$SVC_LOG" >"$FAKE_HOST_STOP"
printf '#!/usr/bin/env bash\necho host-start >>"%s"\n' "$SVC_LOG" >"$FAKE_HOST_START"
chmod +x "$FAKE_SVC_SETUP" "$FAKE_HOST_STOP" "$FAKE_HOST_START"
export SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT="$FAKE_SVC_SETUP"
export SOLAR_CLIENT_HOST_STOP_SCRIPT="$FAKE_HOST_STOP"
export SOLAR_CLIENT_HOST_START_SCRIPT="$FAKE_HOST_START"

: >"$SVC_LOG"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host"
svc_out="$(solar_client_restart_running_services "$MOCK_INSTALL_ROOT" 2>&1)"
assert_ok "restart: gateway restarted with --restart" grep -qx 'gateway --restart' "$SVC_LOG"
assert_ok "restart: console stopped then started" \
  test "$(grep -E '^host-' "$SVC_LOG" | paste -sd, -)" = "host-stop,host-start"
assert_ok "restart: reports both services" \
  bash -c 'grep -q "OK: transport gateway restarted" <<<"$1" && grep -q "OK: console restarted" <<<"$1"' _ "$svc_out"

: >"$SVC_LOG"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="host"
solar_client_restart_running_services "$MOCK_INSTALL_ROOT" >/dev/null 2>&1
assert_ok "restart: a stopped gateway is not started" bash -c '! grep -q gateway "$1"' _ "$SVC_LOG"

: >"$SVC_LOG"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="none"
none_out="$(solar_client_restart_running_services "$MOCK_INSTALL_ROOT" 2>&1)"
assert_ok "restart: nothing running runs nothing" test ! -s "$SVC_LOG"
assert_ok "restart: nothing running is reported" grep -q 'none running' <<<"$none_out"

: >"$SVC_LOG"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host"
SOLAR_CLIENT_GATEWAY_RESTARTED=true solar_client_restart_running_services "$MOCK_INSTALL_ROOT" >/dev/null 2>&1
assert_ok "restart: gateway not restarted twice after LaunchAgent reinstall" \
  bash -c '! grep -q gateway "$1" && grep -q host-start "$1"' _ "$SVC_LOG"

printf '#!/usr/bin/env bash\nexit 1\n' >"$FAKE_SVC_SETUP"
set +e
svc_fail_out="$(solar_client_restart_running_services "$MOCK_INSTALL_ROOT" 2>&1)"
svc_fail_ec=$?
set -e
assert_ok "restart: failure returns non-zero" test "$svc_fail_ec" -ne 0
assert_ok "restart: failure prints the manual command" grep -q -- '--restart' <<<"$svc_fail_out"
unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT
unset SOLAR_CLIENT_HOST_STOP_SCRIPT SOLAR_CLIENT_HOST_START_SCRIPT

# --- detection is scoped to this install (another Solar install may be running) ---
PS_FILE="$TMP/ps.txt"
INSTALL_A="$TMP/install-a"
INSTALL_B="$TMP/install-b"
mkdir -p "$INSTALL_A" "$INSTALL_B"
cat >"$PS_FILE" <<EOF
/usr/bin/python3 $INSTALL_A/core/skills/solar-gateway/scripts/run_http_webhook_bridge.py
/usr/bin/python3 -u $INSTALL_A/core/skills/solar-app/scripts/host_server.py
uv run python3 $INSTALL_B/core/skills/solar-gateway/scripts/run_websocket_bridge.py
EOF
export SOLAR_CLIENT_PS_OUTPUT_FILE="$PS_FILE"
unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE
assert_ok "detect: install A runs gateway and console" \
  test "$(solar_client_running_services "$INSTALL_A" | paste -sd, -)" = "gateway,host"
assert_ok "detect: install B runs only its gateway" \
  test "$(solar_client_running_services "$INSTALL_B" | paste -sd, -)" = "gateway"
assert_ok "detect: another install's services are not ours" \
  test -z "$(solar_client_running_services "$TMP/install-c")"
: >"$SVC_LOG"
printf '#!/usr/bin/env bash\necho "gateway $*" >>"%s"\n' "$SVC_LOG" >"$FAKE_SVC_SETUP"
export SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT="$FAKE_SVC_SETUP"
solar_client_restart_running_services "$TMP/install-c" >/dev/null 2>&1
assert_ok "detect: nothing restarted for an install with no services" test ! -s "$SVC_LOG"
unset SOLAR_CLIENT_PS_OUTPUT_FILE SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT

# --- first update from the published updater, which calls the cutover ---
# v1 is HEAD's client_update.sh: it reloads the new client_lib and restarts.
# The new cutover migrates before it starts anything.
WS_UP="$TMP/ws-up"
INSTALL_UP="$WS_UP/solar"
UP_LIB="$INSTALL_UP/core/skills/solar-client/scripts/client_lib.sh"
UP_UPDATE="$INSTALL_UP/core/skills/solar-client/scripts/client_update.sh"
REPO_ROOT="$(cd "$CORE_ROOT/.." && pwd)"
# The updater these transition cases simulate: the last release without the
# owner gate. A fixed tag, not HEAD, so the cases mean the same after commit.
PREVIOUS_UPDATER_REF="v0.26.1"
git -C "$REPO_ROOT" rev-parse -q --verify "${PREVIOUS_UPDATER_REF}^{commit}" >/dev/null || {
  echo "FATAL: tag $PREVIOUS_UPDATER_REF not found (fetch tags: git fetch --tags)" >&2
  exit 1
}
mkdir -p "$WS_UP/sun" "$WS_UP/.solar" "$INSTALL_UP/core/skills"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"v0.0.1","core_commit":"unknown","core_source":"global"}' >"$WS_UP/.solar/settings.json"
cp -R "$CORE_ROOT/skills/solar-client" "$INSTALL_UP/core/skills/"
cp -R "$CORE_ROOT/skills/solar-paths" "$INSTALL_UP/core/skills/"
rm -rf "$INSTALL_UP/core/skills/solar-client/scripts/__pycache__"
rm -rf "$INSTALL_UP/core/skills/solar-paths/scripts/__pycache__"
git -C "$REPO_ROOT" show "${PREVIOUS_UPDATER_REF}:core/skills/solar-client/scripts/client_update.sh" >"$UP_UPDATE"
git -C "$REPO_ROOT" show "${PREVIOUS_UPDATER_REF}:core/skills/solar-client/scripts/client_lib.sh" >"$UP_LIB"
assert_ok "published updater calls the cutover" \
  bash -c 'grep -q solar_client_state_cutover "$1"' _ "$UP_UPDATE"
git -C "$INSTALL_UP" init -q
git -C "$INSTALL_UP" config user.email "test@test"
git -C "$INSTALL_UP" config user.name "Test"
git -C "$INSTALL_UP" add -A && git -C "$INSTALL_UP" commit -q -m "v1" && git -C "$INSTALL_UP" tag v0.0.1
cp "$UPDATE_SCRIPT" "$UP_UPDATE"
cp "$CORE_ROOT/skills/solar-client/scripts/client_lib.sh" "$UP_LIB"
git -C "$INSTALL_UP" add -A
# The published scripts already call the cutover, so this copy can be empty.
if git -C "$INSTALL_UP" diff --cached --quiet; then
  git -C "$INSTALL_UP" commit -q --allow-empty -m "v2"
else
  git -C "$INSTALL_UP" commit -q -m "v2"
fi
git -C "$INSTALL_UP" tag v0.0.2
git -C "$INSTALL_UP" checkout -q v0.0.1
PUBLISHED_MARK="$TMP/published-cutover.txt"
PUBLISHED_CUT="$TMP/published-cutover.py"
PUBLISHED_LAUNCH="$TMP/published-launchctl.sh"
cat >"$PUBLISHED_CUT" <<EOF
#!/usr/bin/env python3
import pathlib, sys
pathlib.Path("$PUBLISHED_MARK").write_text(" ".join(sys.argv[1:]))
raise SystemExit(0)
EOF
printf '#!/usr/bin/env bash\nexit 1\n' >"$PUBLISHED_LAUNCH"
chmod +x "$PUBLISHED_CUT" "$PUBLISHED_LAUNCH"
set +e
up_out="$(SOLAR_ROOT="$INSTALL_UP" \
  SOLAR_RUNTIME_ROOT="$TMP/published-runtime" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_CUTOVER_SCRIPT="$PUBLISHED_CUT" \
  SOLAR_CLIENT_CUTOVER_ROOT="$TMP/runtime-copy" \
  SOLAR_CLIENT_LAUNCHCTL="$PUBLISHED_LAUNCH" \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$UP_UPDATE" --workspace "$WS_UP" --ref v0.0.2 --yes 2>&1)"
up_ec=$?
set -e
assert_ok "update from the published updater exits 0" test "$up_ec" -eq 0
assert_ok "update moved the install to the new version" \
  test "$(git -C "$INSTALL_UP" rev-parse HEAD)" = "$(git -C "$INSTALL_UP" rev-parse v0.0.2)"
assert_ok "published updater migrated through the new restart" \
  grep -qx "migrate --root $TMP/runtime-copy" "$PUBLISHED_MARK"
[[ "$up_ec" -eq 0 ]] || echo "$up_out" >&2
unset SOLAR_CLIENT_CUTOVER_SCRIPT SOLAR_CLIENT_CUTOVER_ROOT SOLAR_CLIENT_LAUNCHCTL
unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE SOLAR_CLIENT_CUTOVER_DONE

# --- old updater, incompatible owner: new code lands, claim refuses before any stop ---
# v1 has no claim before the install. After checkout it reloads the new lib, and
# that cutover claims before it stops anything. A foreign owner must leave the
# owner file and the runtime as they were.
WS_BAD="$TMP/ws-bad-owner"
INSTALL_BAD="$WS_BAD/solar"
BAD_RT="$TMP/bad-owner-runtime"
BAD_LIB="$INSTALL_BAD/core/skills/solar-client/scripts/client_lib.sh"
BAD_UPDATE="$INSTALL_BAD/core/skills/solar-client/scripts/client_update.sh"
BAD_STOP_LOG="$TMP/bad-owner-stop.log"
BAD_MIGRATE="$TMP/bad-owner-migrate.txt"
mkdir -p "$WS_BAD/sun" "$WS_BAD/.solar" "$INSTALL_BAD/core/skills" "$BAD_RT"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"v0.0.1","core_commit":"unknown","core_source":"global","workspace_id":"settings-id"}' \
  >"$WS_BAD/.solar/settings.json"
WS_BAD="$(cd "$WS_BAD" && pwd -P)"
python3 - <<PY
import json
from pathlib import Path
Path("$BAD_RT/workspace-owner.json").write_text(json.dumps({
    "workspace_id": "owner-id", "path": "$WS_BAD", "claimed_at": "t"}) + "\n")
Path("$BAD_RT/sentinel").write_text("untouched\n")
PY
cp -R "$CORE_ROOT/skills/solar-client" "$INSTALL_BAD/core/skills/"
cp -R "$CORE_ROOT/skills/solar-paths" "$INSTALL_BAD/core/skills/"
rm -rf "$INSTALL_BAD/core/skills/solar-client/scripts/__pycache__"
rm -rf "$INSTALL_BAD/core/skills/solar-paths/scripts/__pycache__"
git -C "$REPO_ROOT" show "${PREVIOUS_UPDATER_REF}:core/skills/solar-client/scripts/client_update.sh" >"$BAD_UPDATE"
git -C "$REPO_ROOT" show "${PREVIOUS_UPDATER_REF}:core/skills/solar-client/scripts/client_lib.sh" >"$BAD_LIB"
git -C "$INSTALL_BAD" init -q
git -C "$INSTALL_BAD" config user.email "test@test"
git -C "$INSTALL_BAD" config user.name "Test"
git -C "$INSTALL_BAD" add -A && git -C "$INSTALL_BAD" commit -q -m "v1" && git -C "$INSTALL_BAD" tag v0.0.1
cp "$UPDATE_SCRIPT" "$BAD_UPDATE"
cp "$CORE_ROOT/skills/solar-client/scripts/client_lib.sh" "$BAD_LIB"
git -C "$INSTALL_BAD" add -A && git -C "$INSTALL_BAD" commit -q -m "v2" && git -C "$INSTALL_BAD" tag v0.0.2
git -C "$INSTALL_BAD" checkout -q v0.0.1
BAD_OWNER_BEFORE="$(cat "$BAD_RT/workspace-owner.json")"
printf '#!/usr/bin/env bash\necho "$*" >>"%s"\nexit 0\n' "$BAD_STOP_LOG" >"$TMP/bad-owner-stop.sh"
printf '#!/usr/bin/env python3\nimport pathlib, sys\npathlib.Path("%s").write_text(" ".join(sys.argv[1:]))\nraise SystemExit(0)\n' \
  "$BAD_MIGRATE" >"$TMP/bad-owner-cutover.py"
chmod +x "$TMP/bad-owner-stop.sh" "$TMP/bad-owner-cutover.py"
: >"$BAD_STOP_LOG"
set +e
bad_out="$(SOLAR_ROOT="$INSTALL_BAD" \
  SOLAR_RUNTIME_ROOT="$BAD_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_CUTOVER_SCRIPT="$TMP/bad-owner-cutover.py" \
  SOLAR_CLIENT_HOST_STOP_SCRIPT="$TMP/bad-owner-stop.sh" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/bad-owner-stop.sh" \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=host \
  bash "$BAD_UPDATE" --workspace "$WS_BAD" --ref v0.0.2 --yes 2>&1)"
bad_ec=$?
set -e
assert_ok "incompatible owner: update exits non-zero" test "$bad_ec" -ne 0
assert_ok "incompatible owner: the new code is installed" \
  test "$(git -C "$INSTALL_BAD" rev-parse HEAD)" = "$(git -C "$INSTALL_BAD" rev-parse v0.0.2)"
assert_ok "incompatible owner: claim refuses before stopping" grep -q 'not stopped' <<<"$bad_out"
assert_ok "incompatible owner: stop was not called" test ! -s "$BAD_STOP_LOG"
assert_ok "incompatible owner: migrate did not run" test ! -f "$BAD_MIGRATE"
assert_ok "incompatible owner: owner file is unchanged" \
  bash -c 'test "$(cat "$1")" = "$2"' _ "$BAD_RT/workspace-owner.json" "$BAD_OWNER_BEFORE"
assert_ok "incompatible owner: settings id is unchanged" \
  grep -q 'settings-id' "$WS_BAD/.solar/settings.json"
assert_ok "incompatible owner: runtime was not migrated" \
  bash -c 'test -f "$1/sentinel" && test ! -f "$1/state.sqlite" && test ! -f "$1/STATE_FORMAT" && test ! -f "$1/state-cutover.json"' _ "$BAD_RT"
[[ "$bad_ec" -ne 0 ]] || echo "$bad_out" >&2
unset SOLAR_CLIENT_CUTOVER_SCRIPT SOLAR_CLIENT_HOST_STOP_SCRIPT SOLAR_CLIENT_LAUNCHCTL
unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE SOLAR_CLIENT_STATE_PY SOLAR_RUNTIME_ROOT

usage_out="$(bash "$UPDATE_SCRIPT" -h 2>&1)"
assert_ok "usage lists --no-restart" grep -q -- '--no-restart' <<<"$usage_out"
assert_ok "usage lists --restart" grep -q -- '  --restart ' <<<"$usage_out"

# --- state cutover: stop, migrate, start; a failed migrate does not start ---
CUT_LOG="$TMP/cutover.log"
FAKE_CUT="$TMP/cutover.py"
FAKE_LAUNCH="$TMP/launchctl.sh"
FAKE_GSTOP="$TMP/gateway-stop.sh"
cat >"$FAKE_CUT" <<EOF
#!/usr/bin/env python3
import pathlib, sys
pathlib.Path("$CUT_LOG").write_text(" ".join(sys.argv[1:]))
raise SystemExit(0)
EOF
printf '#!/usr/bin/env bash\necho "launchctl $*" >>"%s"\n[[ "$1" == print ]] && exit 0\nexit 0\n' "$SVC_LOG" >"$FAKE_LAUNCH"
printf '#!/usr/bin/env bash\necho gateway-stop >>"%s"\n' "$SVC_LOG" >"$FAKE_GSTOP"
chmod +x "$FAKE_CUT" "$FAKE_LAUNCH" "$FAKE_GSTOP"
export SOLAR_RUNTIME_ROOT="$TMP/cutover-runtime"
export SOLAR_WORKSPACE="$TMP/cutover-ws"
export SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py"
mkdir -p "$SOLAR_WORKSPACE/.solar" "$SOLAR_RUNTIME_ROOT"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"v0.0.1","core_commit":"unknown","core_source":"global"}' \
  >"$SOLAR_WORKSPACE/.solar/settings.json"
: >"$SVC_LOG"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="gateway,host"
export SOLAR_CLIENT_CUTOVER_SCRIPT="$FAKE_CUT"
export SOLAR_CLIENT_CUTOVER_ROOT="$TMP/runtime-copy"
export SOLAR_CLIENT_LAUNCHCTL="$FAKE_LAUNCH"
export SOLAR_CLIENT_GATEWAY_STOP_SCRIPT="$FAKE_GSTOP"
export SOLAR_CLIENT_HOST_STOP_SCRIPT="$FAKE_HOST_STOP"
export SOLAR_CLIENT_HOST_START_SCRIPT="$FAKE_HOST_START"
export SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT="$FAKE_SVC_SETUP"
cut_out="$(solar_client_state_cutover "$MOCK_INSTALL_ROOT" auto 2>&1)"
assert_ok "cutover migrates the given root" grep -qx "migrate --root $TMP/runtime-copy" "$CUT_LOG"
assert_ok "cutover stops before it migrates" grep -q 'stopping console' <<<"$cut_out"
order="$(grep -nE 'host-stop|gateway-stop|host-start|gateway --restart|launchctl bootout|launchctl bootstrap' "$SVC_LOG" | tr '\n' ' ')"
assert_ok "cutover order is stop then start" bash -c '[[ "$1" == *host-stop* && "$1" == *host-start* ]]' _ "$order"
stop_line="$(grep -n 'host-stop' "$SVC_LOG" | head -1 | cut -d: -f1)"
start_line="$(grep -n 'host-start' "$SVC_LOG" | head -1 | cut -d: -f1)"
assert_ok "console starts only after it stopped" test "$stop_line" -lt "$start_line"
: >"$SVC_LOG"
printf '#!/usr/bin/env python3\nimport sys\nraise SystemExit(1)\n' >"$FAKE_CUT"
set +e
solar_client_state_cutover "$MOCK_INSTALL_ROOT" auto >/dev/null 2>&1
fail_ec=$?
set -e
assert_ok "a failed migration returns non-zero" test "$fail_ec" -ne 0
assert_ok "a failed migration does not start the console" bash -c '! grep -q host-start "$1"' _ "$SVC_LOG"
unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE SOLAR_CLIENT_CUTOVER_SCRIPT SOLAR_CLIENT_CUTOVER_ROOT
unset SOLAR_CLIENT_LAUNCHCTL SOLAR_CLIENT_GATEWAY_STOP_SCRIPT
unset SOLAR_CLIENT_HOST_STOP_SCRIPT SOLAR_CLIENT_HOST_START_SCRIPT SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT

# --- cutover marker: same identity skips, a new one does not, failure writes nothing ---
MARK_RT="$TMP/marker-runtime"
MARK_WS="$TMP/marker-ws"
MARK_INSTALL="$TMP/marker-install"
mkdir -p "$MARK_RT" "$MARK_WS/sun" "$MARK_WS/.solar" "$MARK_INSTALL/core"
printf '%s\n' 'core' >"$MARK_INSTALL/core/AGENTS.md"
git -C "$MARK_INSTALL" init -q
git -C "$MARK_INSTALL" config user.email "test@test"
git -C "$MARK_INSTALL" config user.name "Test"
git -C "$MARK_INSTALL" add -A && git -C "$MARK_INSTALL" commit -q -m "one"
MARK_COMMIT="$(git -C "$MARK_INSTALL" rev-parse HEAD)"
printf '%s\n' "{\"layout\":\"solar-client-v1.2\",\"core_source\":\"global\",\"core_commit\":\"$MARK_COMMIT\",\"workspace_id\":\"marker-ws\"}" \
  >"$MARK_WS/.solar/settings.json"
printf '%s\n' sqlite >"$MARK_RT/STATE_FORMAT"
export SOLAR_RUNTIME_ROOT="$MARK_RT"
export SOLAR_WORKSPACE="$MARK_WS"
export SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py"
MARK_LOG="$TMP/marker-cutover.log"
MARK_SVC="$TMP/marker-svc.log"
cat >"$TMP/marker-cutover.py" <<EOF
#!/usr/bin/env python3
import pathlib, sys
pathlib.Path("$MARK_LOG").write_text(" ".join(sys.argv[1:]))
raise SystemExit(0)
EOF
printf '#!/usr/bin/env bash\necho "$*" >>"%s"\nexit 0\n' "$MARK_SVC" >"$TMP/marker-launch.sh"
chmod +x "$TMP/marker-cutover.py" "$TMP/marker-launch.sh"
export SOLAR_CLIENT_CUTOVER_SCRIPT="$TMP/marker-cutover.py"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/marker-launch.sh"
export SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none
: >"$MARK_SVC"
solar_client_state_cutover "$MARK_INSTALL" auto >/dev/null
assert_ok "first cutover writes the marker" \
  bash -c 'grep -q "$1" "$2"' _ "$MARK_COMMIT" "$MARK_RT/state-cutover.json"
assert_ok "first cutover migrated" grep -q migrate "$MARK_LOG"
: >"$MARK_LOG"
: >"$MARK_SVC"
skip_out="$(solar_client_state_cutover "$MARK_INSTALL" auto 2>&1)"
assert_ok "same identity does not migrate again" test ! -s "$MARK_LOG"
assert_ok "same identity does not stop services" test ! -s "$MARK_SVC"
assert_ok "same identity says it is not stopping" grep -q 'not stopping' <<<"$skip_out"
printf '%s\n' 'two' >"$MARK_INSTALL/core/AGENTS.md"
git -C "$MARK_INSTALL" add -A && git -C "$MARK_INSTALL" commit -q -m "two"
: >"$MARK_SVC"
solar_client_state_cutover "$MARK_INSTALL" auto >/dev/null
assert_ok "a new commit migrates again" grep -q migrate "$MARK_LOG"
printf '#!/usr/bin/env python3\nimport sys\nraise SystemExit(1)\n' >"$TMP/marker-cutover.py"
rm -f "$MARK_RT/state-cutover.json"
: >"$MARK_SVC"
set +e
solar_client_state_cutover "$MARK_INSTALL" auto >/dev/null 2>&1
mark_fail=$?
set -e
assert_ok "a failed migrate returns non-zero" test "$mark_fail" -ne 0
assert_ok "a failed migrate leaves no marker" test ! -f "$MARK_RT/state-cutover.json"
python3 - <<PY
import json
from pathlib import Path
Path("$MARK_RT/workspace-owner.json").write_text(json.dumps({
    "workspace_id": "someone-else", "path": "$MARK_WS", "claimed_at": "t"}) + "\n")
PY
: >"$MARK_SVC"
set +e
solar_client_state_cutover "$MARK_INSTALL" auto >/dev/null 2>&1
refused=$?
set -e
assert_ok "a refused claim returns non-zero" test "$refused" -ne 0
assert_ok "a refused claim does not stop services" test ! -s "$MARK_SVC"

# Portable identity is the bundle checksum, not core_commit.
PORT_RT="$TMP/portable-runtime"
mkdir -p "$PORT_RT"
printf '%s\n' sqlite >"$PORT_RT/STATE_FORMAT"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_commit":"stale","bundle_checksum":"chk-1","workspace_id":"marker-ws"}' \
  >"$MARK_WS/.solar/settings.json"
export SOLAR_RUNTIME_ROOT="$PORT_RT"
python3 "$SOLAR_CLIENT_STATE_PY" owner claim --workspace "$MARK_WS" --id marker-ws >/dev/null
python3 - <<PY
import json
from pathlib import Path
Path("$PORT_RT/state-cutover.json").write_text(json.dumps({"identity": "chk-1", "format": "sqlite"}) + "\n")
PY
: >"$MARK_LOG"
port_out="$(solar_client_state_cutover "$MARK_INSTALL" auto 2>&1)"
assert_ok "the same bundle checksum does not cut over" test ! -s "$MARK_LOG"
assert_ok "the same bundle checksum does not stop" grep -q 'not stopping' <<<"$port_out"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_commit":"stale","bundle_checksum":"chk-2","workspace_id":"marker-ws"}' \
  >"$MARK_WS/.solar/settings.json"
cat >"$TMP/marker-cutover.py" <<EOF
#!/usr/bin/env python3
import pathlib, sys
pathlib.Path("$MARK_LOG").write_text(" ".join(sys.argv[1:]))
raise SystemExit(0)
EOF
chmod +x "$TMP/marker-cutover.py"
: >"$MARK_LOG"
solar_client_state_cutover "$MARK_INSTALL" auto >/dev/null
assert_ok "a changed bundle checksum cuts over" grep -q migrate "$MARK_LOG"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_commit":"stale","workspace_id":"marker-ws"}' \
  >"$MARK_WS/.solar/settings.json"
rm -f "$PORT_RT/state-cutover.json"
: >"$MARK_LOG"
solar_client_state_cutover "$MARK_INSTALL" auto >/dev/null
assert_ok "a missing bundle checksum still cuts over" grep -q migrate "$MARK_LOG"

unset SOLAR_RUNTIME_ROOT SOLAR_WORKSPACE SOLAR_CLIENT_STATE_PY SOLAR_CLIENT_CUTOVER_SCRIPT
unset SOLAR_CLIENT_LAUNCHCTL SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE

# --- cutover checks the install before it stops anything ---
PRE_RT="$TMP/preflight-runtime"
PRE_WS="$TMP/preflight-ws"
PRE_INSTALL="$TMP/preflight-install"
PRE_LOG="$TMP/preflight-stop.log"
mkdir -p "$PRE_RT" "$PRE_WS/sun" "$PRE_WS/.solar" "$PRE_INSTALL/core"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"global","core_version":"v0","workspace_id":"preflight-ws"}' \
  >"$PRE_WS/.solar/settings.json"
printf '#!/usr/bin/env bash\necho "$*" >>"%s"\nexit 0\n' "$PRE_LOG" >"$TMP/preflight-stop.sh"
chmod +x "$TMP/preflight-stop.sh"
: >"$PRE_LOG"
set +e
pre_out="$(
  unset SOLAR_CLIENT_CUTOVER_SCRIPT SOLAR_CLIENT_STATE_PY SOLAR_CLIENT_CUTOVER_ROOT
  SOLAR_WORKSPACE="$PRE_WS" \
  SOLAR_RUNTIME_ROOT="$PRE_RT" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/preflight-stop.sh" \
  SOLAR_CLIENT_HOST_STOP_SCRIPT="$TMP/preflight-stop.sh" \
  SOLAR_CLIENT_GATEWAY_STOP_SCRIPT="$TMP/preflight-stop.sh" \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=host \
  solar_client_state_cutover "$PRE_INSTALL" auto 2>&1
)"
pre_ec=$?
set -e
assert_ok "incomplete solar-state exits non-zero" test "$pre_ec" -ne 0
assert_ok "incomplete solar-state does not stop services" grep -q 'Services were not stopped' <<<"$pre_out"
assert_ok "incomplete solar-state stop log is empty" test ! -s "$PRE_LOG"
assert_ok "incomplete solar-state does not claim the runtime" test ! -f "$PRE_RT/workspace-owner.json"
[[ "$pre_ec" -ne 0 ]] || echo "$pre_out" >&2

# --- portable update refuses when no global install exists ---
PORT_WS="$TMP/portable-none-ws"
PORT_RT="$TMP/portable-none-runtime"
PORT_LOG="$TMP/portable-none-launch.log"
mkdir -p "$PORT_WS/sun" "$PORT_WS/.solar/bundle/core/skills/solar-paths/scripts" \
  "$PORT_WS/.solar/bundle/core/skills/solar-client/scripts" "$PORT_RT"
printf '%s\n' '#!/usr/bin/env bash' >"$PORT_WS/.solar/bundle/core/skills/solar-paths/scripts/resolve_solar_paths.sh"
printf '%s\n' '#!/usr/bin/env bash' >"$PORT_WS/.solar/bundle/core/skills/solar-client/scripts/sync-clients.sh"
printf '%s\n' '{"stub":true}' >"$PORT_WS/.solar/bundle/index.json"
printf '%s\n' 'keep' >"$PORT_WS/.solar/bundle/STUB"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_version":"v0","bundle_checksum":"stub"}' \
  >"$PORT_WS/.solar/settings.json"
printf '#!/usr/bin/env bash\necho "$*" >>"%s"\nexit 1\n' "$PORT_LOG" >"$TMP/portable-none-launch.sh"
chmod +x "$TMP/portable-none-launch.sh"
: >"$PORT_LOG"
set +e
none_out="$(
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="" \
  SOLAR_RUNTIME_ROOT="$PORT_RT" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/portable-none-launch.sh" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$UPDATE_SCRIPT" --workspace "$PORT_WS" --check 2>&1
)"
none_ec=$?
set -e
assert_ok "portable update without a global install exits non-zero" test "$none_ec" -ne 0
assert_ok "portable update without a global install says nothing changed" grep -q 'Nothing was changed' <<<"$none_out"
assert_ok "portable update without a global install keeps the stub bundle" test -f "$PORT_WS/.solar/bundle/STUB"
assert_ok "portable update without a global install keeps snapshot settings" grep -q workspace-snapshot "$PORT_WS/.solar/settings.json"
assert_ok "portable update without a global install does not claim" test ! -f "$PORT_RT/workspace-owner.json"
assert_ok "portable update without a global install does not call launchctl" test ! -s "$PORT_LOG"

# --- portable update retargets the global install and regenerates the bundle ---
PORT_OK_WS="$TMP/portable-ok-ws"
PORT_OK_RT="$TMP/portable-ok-runtime"
PORT_OK_INSTALL="$TMP/portable-ok-install"
PORT_OK_LOG="$TMP/portable-ok-launch.log"
mkdir -p "$PORT_OK_WS/sun" "$PORT_OK_WS/.solar/bundle/core/skills/solar-paths/scripts" \
  "$PORT_OK_WS/.solar/bundle/core/skills/solar-client/scripts" "$PORT_OK_RT" "$PORT_OK_INSTALL"
printf '%s\n' '#!/usr/bin/env bash' >"$PORT_OK_WS/.solar/bundle/core/skills/solar-paths/scripts/resolve_solar_paths.sh"
printf '%s\n' '#!/usr/bin/env bash' >"$PORT_OK_WS/.solar/bundle/core/skills/solar-client/scripts/sync-clients.sh"
printf '%s\n' '{"stub":true}' >"$PORT_OK_WS/.solar/bundle/index.json"
printf '%s\n' 'keep' >"$PORT_OK_WS/.solar/bundle/STUB"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_version":"v0.0.1","bundle_checksum":"stub","requires_global_client":false}' \
  >"$PORT_OK_WS/.solar/settings.json"
cp -R "$CORE_ROOT" "$PORT_OK_INSTALL/core"
rm -rf "$PORT_OK_INSTALL/core/skills/solar-client/scripts/__pycache__" \
  "$PORT_OK_INSTALL/core/skills/solar-paths/scripts/__pycache__" \
  "$PORT_OK_INSTALL/core/skills/solar-state/scripts/__pycache__"
printf '%s\n' 'OLD' >"$PORT_OK_INSTALL/core/.portable-marker"
git -C "$PORT_OK_INSTALL" init -q
git -C "$PORT_OK_INSTALL" config user.email "test@test"
git -C "$PORT_OK_INSTALL" config user.name "Test"
git -C "$PORT_OK_INSTALL" add -A && git -C "$PORT_OK_INSTALL" commit -q -m "v1" && git -C "$PORT_OK_INSTALL" tag v0.0.1
printf '%s\n' 'NEW' >"$PORT_OK_INSTALL/core/.portable-marker"
git -C "$PORT_OK_INSTALL" add -A && git -C "$PORT_OK_INSTALL" commit -q -m "v2" && git -C "$PORT_OK_INSTALL" tag v0.0.2
git -C "$PORT_OK_INSTALL" checkout -q v0.0.1
printf '#!/usr/bin/env python3\nimport sys\nraise SystemExit(0)\n' >"$TMP/portable-ok-cutover.py"
printf '#!/usr/bin/env bash\ncase "$1" in print) exit 1 ;; *) echo "$*" >>"%s"; exit 1 ;; esac\n' "$PORT_OK_LOG" >"$TMP/portable-ok-launch.sh"
chmod +x "$TMP/portable-ok-cutover.py" "$TMP/portable-ok-launch.sh"
: >"$PORT_OK_LOG"
set +e
ok_out="$(
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$PORT_OK_INSTALL" \
  SOLAR_RUNTIME_ROOT="$PORT_OK_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_CUTOVER_SCRIPT="$TMP/portable-ok-cutover.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/portable-ok-launch.sh" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$UPDATE_SCRIPT" --workspace "$PORT_OK_WS" --ref v0.0.2 --yes 2>&1
)"
ok_ec=$?
set -e
port_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PORT_OK_INSTALL")"
assert_ok "portable update exits 0" test "$ok_ec" -eq 0
assert_ok "portable update uses git-repo mode" grep -q 'mode=git-repo' <<<"$ok_out"
assert_ok "portable update does not treat the bundle as the install" bash -c '! grep -q mode=bundle-core <<<"$1"' _ "$ok_out"
assert_ok "portable update names the global install" grep -q "SOLAR_ROOT=$port_abs" <<<"$ok_out"
assert_ok "portable update checks out the global install" grep -qx 'NEW' "$PORT_OK_INSTALL/core/.portable-marker"
assert_ok "portable update regenerates the bundle" test ! -f "$PORT_OK_WS/.solar/bundle/STUB"
assert_ok "regenerated bundle contains solar-state" test -f "$PORT_OK_WS/.solar/bundle/core/skills/solar-state/scripts/solar_state_cutover.py"
assert_ok "portable update leaves settings on the snapshot" grep -q workspace-snapshot "$PORT_OK_WS/.solar/settings.json"
assert_ok "portable update does not bootout launchctl" test ! -s "$PORT_OK_LOG"
[[ "$ok_ec" -eq 0 ]] || echo "$ok_out" >&2

# --- portable sync stops and starts the global install's services, not the bundle's ---
SYNC_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/client_sync.sh"
SYNC_WS="$TMP/sync-port-ws"
SYNC_RT="$TMP/sync-port-runtime"
SYNC_GLOBAL="$TMP/sync-port-global"
SYNC_LOG="$TMP/sync-port-services.log"
SYNC_PUB="$TMP/sync-port-published.txt"
mkdir -p "$SYNC_WS/sun" "$SYNC_RT" \
  "$SYNC_WS/.solar/bundle/core/skills/solar-paths/scripts" \
  "$SYNC_WS/.solar/bundle/core/skills/solar-client/scripts" \
  "$SYNC_WS/.solar/bundle/core/skills/solar-app/scripts" \
  "$SYNC_WS/.solar/bundle/core/skills/solar-gateway/scripts" \
  "$SYNC_GLOBAL/core/skills/solar-client/scripts" \
  "$SYNC_GLOBAL/core/skills/solar-app/scripts" \
  "$SYNC_GLOBAL/core/skills/solar-gateway/scripts"
printf '%s\n' '#!/usr/bin/env bash' >"$SYNC_WS/.solar/bundle/core/skills/solar-paths/scripts/resolve_solar_paths.sh"
printf '%s\n' '#!/usr/bin/env bash' 'echo solar-stub' \
  >"$SYNC_WS/.solar/bundle/core/skills/solar-client/scripts/solar"
printf '%s\n' '#!/usr/bin/env bash' "printf '%s\n' \"published \$0\" >>\"$SYNC_PUB\"" \
  >"$SYNC_WS/.solar/bundle/core/skills/solar-client/scripts/sync-clients.sh"
printf '%s\n' '{"stub":true}' >"$SYNC_WS/.solar/bundle/index.json"
printf '%s\n' '#!/usr/bin/env bash' 'echo solar' \
  >"$SYNC_GLOBAL/core/skills/solar-client/scripts/solar"
chmod +x "$SYNC_WS/.solar/bundle/core/skills/solar-client/scripts/solar" \
  "$SYNC_WS/.solar/bundle/core/skills/solar-client/scripts/sync-clients.sh" \
  "$SYNC_GLOBAL/core/skills/solar-client/scripts/solar"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_version":"v0","bundle_checksum":"sync-stub","requires_global_client":false}' \
  >"$SYNC_WS/.solar/settings.json"
_write_svc_logger() {
  local dest="$1" log="$2"
  cat >"$dest" <<EOF
#!/usr/bin/env bash
printf '%s %s\n' "\$0" "\$*" >>"$log"
exit 0
EOF
  chmod +x "$dest"
}
_write_svc_logger "$SYNC_GLOBAL/core/skills/solar-app/scripts/stop_host.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_GLOBAL/core/skills/solar-app/scripts/start_host.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_GLOBAL/core/skills/solar-gateway/scripts/stop_transport_gateway.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_GLOBAL/core/skills/solar-gateway/scripts/setup_transport_gateway.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_WS/.solar/bundle/core/skills/solar-app/scripts/stop_host.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_WS/.solar/bundle/core/skills/solar-app/scripts/start_host.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_WS/.solar/bundle/core/skills/solar-gateway/scripts/stop_transport_gateway.sh" "$SYNC_LOG"
_write_svc_logger "$SYNC_WS/.solar/bundle/core/skills/solar-gateway/scripts/setup_transport_gateway.sh" "$SYNC_LOG"
sync_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SYNC_GLOBAL")"
printf '%s\n' \
  "python3 $sync_abs/core/skills/solar-gateway/scripts/run_http_webhook_bridge.py" \
  "python3 $sync_abs/core/skills/solar-app/scripts/host_server.py" \
  >"$TMP/sync-port-ps.txt"
printf '#!/usr/bin/env python3\nimport sys\nraise SystemExit(0)\n' >"$TMP/sync-port-cutover.py"
printf '#!/usr/bin/env bash\ncase "$1" in print) exit 1 ;; *) exit 0 ;; esac\n' >"$TMP/sync-port-launch.sh"
chmod +x "$TMP/sync-port-cutover.py" "$TMP/sync-port-launch.sh"
: >"$SYNC_LOG"
: >"$SYNC_PUB"
set +e
sync_out="$(
  cd "$SYNC_WS"
  unset SOLAR_WORKSPACE SOLAR_ROOT SOLAR_CORE_SOURCE SOLAR_GLOBAL_ROOT
  unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE SOLAR_CLIENT_CUTOVER_ROOT
  unset SOLAR_CLIENT_HOST_STOP_SCRIPT SOLAR_CLIENT_HOST_START_SCRIPT
  unset SOLAR_CLIENT_GATEWAY_STOP_SCRIPT SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$SYNC_GLOBAL" \
  SOLAR_RUNTIME_ROOT="$SYNC_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_CUTOVER_SCRIPT="$TMP/sync-port-cutover.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/sync-port-launch.sh" \
  SOLAR_CLIENT_PS_OUTPUT_FILE="$TMP/sync-port-ps.txt" \
  bash "$SYNC_SCRIPT" 2>&1
)"
sync_ec=$?
set -e
assert_ok "portable sync exits 0" test "$sync_ec" -eq 0
assert_ok "portable sync publishes IDE links from the bundle" grep -q '.solar/bundle' "$SYNC_PUB"
assert_ok "portable sync stops the global console" grep -q "$sync_abs/core/skills/solar-app/scripts/stop_host.sh" "$SYNC_LOG"
assert_ok "portable sync starts the global console" grep -q "$sync_abs/core/skills/solar-app/scripts/start_host.sh" "$SYNC_LOG"
assert_ok "portable sync stops the global gateway" grep -q "$sync_abs/core/skills/solar-gateway/scripts/stop_transport_gateway.sh" "$SYNC_LOG"
assert_ok "portable sync starts the global gateway" grep -q "$sync_abs/core/skills/solar-gateway/scripts/setup_transport_gateway.sh" "$SYNC_LOG"
assert_ok "portable sync never runs stop or start from the bundle" \
  bash -c '! grep -q .solar/bundle "$1"' _ "$SYNC_LOG"
[[ "$sync_ec" -eq 0 ]] || echo "$sync_out" >&2

# --- sync --portable from global mode publishes the bundle and cuts over the global ---
ENTER_WS="$TMP/sync-enter-ws"
ENTER_RT="$TMP/sync-enter-runtime"
ENTER_GLOBAL="$TMP/sync-enter-global"
ENTER_LOG="$TMP/sync-enter-services.log"
ENTER_CLAIM="$TMP/sync-enter-claim.log"
ENTER_CUT="$TMP/sync-enter-cutover.log"
mkdir -p "$ENTER_WS/sun" "$ENTER_WS/.solar" "$ENTER_RT" "$ENTER_GLOBAL"
printf '%s\n' '{"layout":"solar-client-v1.2","scope":"workspace","core_source":"global","core_version":"v0","core_commit":"abc","requires_global_client":true}' \
  >"$ENTER_WS/.solar/settings.json"
cp -R "$CORE_ROOT" "$ENTER_GLOBAL/core"
rm -rf "$ENTER_GLOBAL/core/skills/solar-client/scripts/__pycache__" \
  "$ENTER_GLOBAL/core/skills/solar-paths/scripts/__pycache__" \
  "$ENTER_GLOBAL/core/skills/solar-state/scripts/__pycache__"
mv "$ENTER_GLOBAL/core/skills/solar-state/scripts/solar_state.py" \
  "$ENTER_GLOBAL/core/skills/solar-state/scripts/solar_state_real.py"
cat >"$ENTER_GLOBAL/core/skills/solar-state/scripts/solar_state.py" <<EOF
#!/usr/bin/env python3
import pathlib, runpy, sys
log = pathlib.Path("$ENTER_CLAIM")
with log.open("a", encoding="utf-8") as fh:
    fh.write(str(pathlib.Path(__file__).resolve()) + "\\n")
real = pathlib.Path(__file__).resolve().with_name("solar_state_real.py")
sys.argv[0] = str(real)
runpy.run_path(str(real), run_name="__main__")
EOF
cat >"$ENTER_GLOBAL/core/skills/solar-state/scripts/solar_state_cutover.py" <<EOF
#!/usr/bin/env python3
import pathlib, sys
pathlib.Path("$ENTER_CUT").write_text(str(pathlib.Path(__file__).resolve()) + "\\n")
raise SystemExit(0)
EOF
chmod +x "$ENTER_GLOBAL/core/skills/solar-state/scripts/solar_state.py" \
  "$ENTER_GLOBAL/core/skills/solar-state/scripts/solar_state_cutover.py"
_write_svc_logger "$ENTER_GLOBAL/core/skills/solar-app/scripts/stop_host.sh" "$ENTER_LOG"
_write_svc_logger "$ENTER_GLOBAL/core/skills/solar-app/scripts/start_host.sh" "$ENTER_LOG"
_write_svc_logger "$ENTER_GLOBAL/core/skills/solar-gateway/scripts/stop_transport_gateway.sh" "$ENTER_LOG"
_write_svc_logger "$ENTER_GLOBAL/core/skills/solar-gateway/scripts/setup_transport_gateway.sh" "$ENTER_LOG"
enter_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ENTER_GLOBAL")"
printf '%s\n' \
  "python3 $enter_abs/core/skills/solar-gateway/scripts/run_http_webhook_bridge.py" \
  "python3 $enter_abs/core/skills/solar-app/scripts/host_server.py" \
  >"$TMP/sync-enter-ps.txt"
printf '#!/usr/bin/env bash\ncase "$1" in print) exit 1 ;; *) exit 0 ;; esac\n' >"$TMP/sync-enter-launch.sh"
chmod +x "$TMP/sync-enter-launch.sh"
: >"$ENTER_LOG"
: >"$ENTER_CLAIM"
: >"$ENTER_CUT"
set +e
enter_out="$(
  cd "$ENTER_WS"
  unset SOLAR_WORKSPACE SOLAR_CORE_SOURCE SOLAR_GLOBAL_ROOT CODEX_HOME
  unset SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE SOLAR_CLIENT_CUTOVER_ROOT
  unset SOLAR_CLIENT_STATE_PY SOLAR_CLIENT_CUTOVER_SCRIPT
  unset SOLAR_CLIENT_HOST_STOP_SCRIPT SOLAR_CLIENT_HOST_START_SCRIPT
  unset SOLAR_CLIENT_GATEWAY_STOP_SCRIPT SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT
  SOLAR_ROOT="$ENTER_GLOBAL" \
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$ENTER_GLOBAL" \
  SOLAR_RUNTIME_ROOT="$ENTER_RT" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/sync-enter-launch.sh" \
  SOLAR_CLIENT_PS_OUTPUT_FILE="$TMP/sync-enter-ps.txt" \
  bash "$SYNC_SCRIPT" --portable 2>&1
)"
enter_ec=$?
set -e
assert_ok "sync --portable from global exits 0" test "$enter_ec" -eq 0
assert_ok "sync --portable from global switches settings to the snapshot" \
  grep -q workspace-snapshot "$ENTER_WS/.solar/settings.json"
assert_ok "sync --portable from global links Claude at the bundle" \
  python3 -c 'import os,sys; t=os.path.realpath(sys.argv[1]); b=os.path.realpath(sys.argv[2]); g=os.path.realpath(sys.argv[3]); raise SystemExit(0 if t.startswith(b+os.sep) and not t.startswith(g+os.sep) else 1)' \
  "$ENTER_WS/.claude/skills/solar-client" "$ENTER_WS/.solar/bundle" "$ENTER_GLOBAL"
assert_ok "sync --portable does not publish a Codex symlink under .codex/skills" \
  bash -c '[[ ! -e "$1" && ! -L "$1" ]]' _ "$ENTER_WS/.codex/skills/solar-client"
assert_ok "sync --portable publishes Codex as a copy under .agents/skills" \
  test -f "$ENTER_WS/.agents/skills/solar-client/SKILL.md"
assert_ok "sync --portable from global links Gemini at the bundle" \
  python3 -c 'import os,sys; t=os.path.realpath(sys.argv[1]); b=os.path.realpath(sys.argv[2]); g=os.path.realpath(sys.argv[3]); raise SystemExit(0 if t.startswith(b+os.sep) and not t.startswith(g+os.sep) else 1)' \
  "$ENTER_WS/.gemini/skills/solar-client" "$ENTER_WS/.solar/bundle" "$ENTER_GLOBAL"
assert_ok "sync --portable from global claims with the global solar-state" \
  grep -q "$enter_abs/core/skills/solar-state/scripts/solar_state.py" "$ENTER_CLAIM"
assert_ok "sync --portable from global does not claim with the bundle" \
  bash -c '! grep -q .solar/bundle "$1"' _ "$ENTER_CLAIM"
assert_ok "sync --portable from global cuts over with the global script" \
  grep -q "$enter_abs/core/skills/solar-state/scripts/solar_state_cutover.py" "$ENTER_CUT"
assert_ok "sync --portable from global does not cut over with the bundle" \
  bash -c '! grep -q .solar/bundle "$1"' _ "$ENTER_CUT"
assert_ok "sync --portable from global stops the global console" \
  grep -q "$enter_abs/core/skills/solar-app/scripts/stop_host.sh" "$ENTER_LOG"
assert_ok "sync --portable from global starts the global console" \
  grep -q "$enter_abs/core/skills/solar-app/scripts/start_host.sh" "$ENTER_LOG"
assert_ok "sync --portable from global stops the global gateway" \
  grep -q "$enter_abs/core/skills/solar-gateway/scripts/stop_transport_gateway.sh" "$ENTER_LOG"
assert_ok "sync --portable from global starts the global gateway" \
  grep -q "$enter_abs/core/skills/solar-gateway/scripts/setup_transport_gateway.sh" "$ENTER_LOG"
assert_ok "sync --portable from global never runs stop or start from the bundle" \
  bash -c '! grep -q .solar/bundle "$1"' _ "$ENTER_LOG"
[[ "$enter_ec" -eq 0 ]] || echo "$enter_out" >&2

# --- portable update of a global install without .git uses bundle-core ---
PORT_NG_WS="$TMP/portable-nongit-ws"
PORT_NG_RT="$TMP/portable-nongit-runtime"
PORT_NG_INSTALL="$TMP/portable-nongit-install"
PORT_NG_LOG="$TMP/portable-nongit-launch.log"
mkdir -p "$PORT_NG_WS/sun" "$PORT_NG_WS/.solar/bundle/core/skills/solar-paths/scripts" \
  "$PORT_NG_WS/.solar/bundle/core/skills/solar-client/scripts" "$PORT_NG_RT" "$PORT_NG_INSTALL"
printf '%s\n' '#!/usr/bin/env bash' >"$PORT_NG_WS/.solar/bundle/core/skills/solar-paths/scripts/resolve_solar_paths.sh"
printf '%s\n' '#!/usr/bin/env bash' >"$PORT_NG_WS/.solar/bundle/core/skills/solar-client/scripts/sync-clients.sh"
printf '%s\n' '{"stub":true}' >"$PORT_NG_WS/.solar/bundle/index.json"
printf '%s\n' 'keep' >"$PORT_NG_WS/.solar/bundle/STUB"
mkdir -p "$PORT_NG_WS/.solar/bundle/core/skills/solar-client"
printf '%s\n' 'FROM_SNAPSHOT' >"$PORT_NG_WS/.solar/bundle/core/skills/solar-client/FROM_SNAPSHOT"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_version":"v0","bundle_checksum":"stub","requires_global_client":false}' \
  >"$PORT_NG_WS/.solar/settings.json"
cp -R "$CORE_ROOT" "$PORT_NG_INSTALL/core"
rm -rf "$PORT_NG_INSTALL/core/skills/solar-client/scripts/__pycache__" \
  "$PORT_NG_INSTALL/core/skills/solar-paths/scripts/__pycache__" \
  "$PORT_NG_INSTALL/core/skills/solar-state/scripts/__pycache__"
printf '%s\n' 'FROM_GLOBAL' >"$PORT_NG_INSTALL/core/skills/solar-client/FROM_GLOBAL"
printf '%s\n' 'leftover' >"$PORT_NG_INSTALL/core/LEFTOVER"
printf '#!/usr/bin/env python3\nimport sys\nraise SystemExit(0)\n' >"$TMP/portable-nongit-cutover.py"
printf '#!/usr/bin/env bash\ncase "$1" in print) exit 1 ;; *) echo "$*" >>"%s"; exit 1 ;; esac\n' "$PORT_NG_LOG" >"$TMP/portable-nongit-launch.sh"
chmod +x "$TMP/portable-nongit-cutover.py" "$TMP/portable-nongit-launch.sh"
: >"$PORT_NG_LOG"
set +e
ng_out="$(
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$PORT_NG_INSTALL" \
  SOLAR_RUNTIME_ROOT="$PORT_NG_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_CUTOVER_SCRIPT="$TMP/portable-nongit-cutover.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/portable-nongit-launch.sh" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$UPDATE_SCRIPT" --workspace "$PORT_NG_WS" --bundle --yes 2>&1
)"
ng_ec=$?
set -e
ng_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PORT_NG_INSTALL")"
ng_bundle_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PORT_NG_WS/.solar/bundle")"
assert_ok "portable update without git exits 0" test "$ng_ec" -eq 0
assert_ok "portable update without git uses bundle-core" grep -q 'mode=bundle-core' <<<"$ng_out"
assert_ok "portable update without git names the global install" grep -q "SOLAR_ROOT=$ng_abs" <<<"$ng_out"
assert_ok "portable update without git does not treat the snapshot as the install" \
  bash -c '! grep -q "SOLAR_ROOT=$1" <<<"$2"' _ "$ng_bundle_abs" "$ng_out"
assert_ok "portable update without git does not refuse for missing .git" \
  bash -c '! grep -q "not a git checkout" <<<"$1"' _ "$ng_out"
assert_ok "portable update without git rsyncs the global core" test ! -f "$PORT_NG_INSTALL/core/LEFTOVER"
assert_ok "portable update without git keeps the global marker" grep -qx 'FROM_GLOBAL' "$PORT_NG_INSTALL/core/skills/solar-client/FROM_GLOBAL"
assert_ok "portable update without git does not copy the snapshot into the global" \
  test ! -f "$PORT_NG_INSTALL/core/skills/solar-client/FROM_SNAPSHOT"
assert_ok "portable update without git regenerates the bundle" test ! -f "$PORT_NG_WS/.solar/bundle/STUB"
assert_ok "regenerated bundle comes from the global install" \
  grep -qx 'FROM_GLOBAL' "$PORT_NG_WS/.solar/bundle/core/skills/solar-client/FROM_GLOBAL"
assert_ok "portable update without git leaves settings on the snapshot" \
  grep -q workspace-snapshot "$PORT_NG_WS/.solar/settings.json"
assert_ok "portable update without git does not bootout launchctl" test ! -s "$PORT_NG_LOG"
[[ "$ng_ec" -eq 0 ]] || echo "$ng_out" >&2

# --- a machine already on the old updater cannot update itself out of the bundle ---
# v0.27.0's client_update.sh sets INSTALL_ROOT=$SOLAR_ROOT, and portable resolve
# makes that the bundle (mode=bundle-core). The fix is checked out in the global
# install directly; bundle create and update come after that.
# A shallow clone or one fetched without tags does not have v0.27.0.
if ! git -C "$REPO_ROOT" rev-parse -q --verify "v0.27.0^{commit}" >/dev/null 2>&1; then
  echo "SKIP: trapped-machine case needs tag v0.27.0 (fetch tags or use a full clone)"
else
TRAP_GLOBAL="$TMP/trapped-global"
TRAP_WS="$TMP/trapped-ws"
TRAP_RT="$TMP/trapped-runtime"
TRAP_LOG="$TMP/trapped-launch.log"
mkdir -p "$TRAP_GLOBAL" "$TRAP_WS/sun" "$TRAP_RT" \
  "$TRAP_WS/.solar/bundle/core/skills/solar-paths/scripts" \
  "$TRAP_WS/.solar/bundle/core/skills/solar-client/scripts"
printf '%s\n' '#!/usr/bin/env bash' \
  >"$TRAP_WS/.solar/bundle/core/skills/solar-paths/scripts/resolve_solar_paths.sh"
printf '%s\n' '#!/usr/bin/env bash' \
  >"$TRAP_WS/.solar/bundle/core/skills/solar-client/scripts/sync-clients.sh"
printf '%s\n' '#!/usr/bin/env bash' 'echo solar-stub' \
  >"$TRAP_WS/.solar/bundle/core/skills/solar-client/scripts/solar"
chmod +x "$TRAP_WS/.solar/bundle/core/skills/solar-client/scripts/solar"
printf '%s\n' '{"stub":true}' >"$TRAP_WS/.solar/bundle/index.json"
printf '%s\n' '{"layout":"solar-client-v1.2","core_source":"workspace-snapshot","core_version":"v0.27.0","bundle_checksum":"stub","requires_global_client":false}' \
  >"$TRAP_WS/.solar/settings.json"
cp -R "$CORE_ROOT" "$TRAP_GLOBAL/core"
rm -rf "$TRAP_GLOBAL/core/skills/solar-client/scripts/__pycache__" \
  "$TRAP_GLOBAL/core/skills/solar-paths/scripts/__pycache__"
git -C "$REPO_ROOT" show "v0.27.0:core/skills/solar-client/scripts/client_update.sh" \
  >"$TRAP_GLOBAL/core/skills/solar-client/scripts/client_update.sh"
printf '%s\n' 'OLD' >"$TRAP_GLOBAL/core/.trapped-marker"
git -C "$TRAP_GLOBAL" init -q
git -C "$TRAP_GLOBAL" config user.email "test@test"
git -C "$TRAP_GLOBAL" config user.name "Test"
git -C "$TRAP_GLOBAL" add -A && git -C "$TRAP_GLOBAL" commit -q -m "v0.27.0 updater" && git -C "$TRAP_GLOBAL" tag v0.0.1
cp "$UPDATE_SCRIPT" "$TRAP_GLOBAL/core/skills/solar-client/scripts/client_update.sh"
cp "$CORE_ROOT/skills/solar-client/scripts/client_lib.sh" \
  "$TRAP_GLOBAL/core/skills/solar-client/scripts/client_lib.sh"
printf '%s\n' 'NEW' >"$TRAP_GLOBAL/core/.trapped-marker"
git -C "$TRAP_GLOBAL" add -A && git -C "$TRAP_GLOBAL" commit -q -m "v0.27.1 updater" && git -C "$TRAP_GLOBAL" tag v0.0.2
git -C "$TRAP_GLOBAL" checkout -q v0.0.1
printf '#!/usr/bin/env bash\ncase "$1" in print) exit 1 ;; *) echo "$*" >>"%s"; exit 1 ;; esac\n' "$TRAP_LOG" \
  >"$TMP/trapped-launch.sh"
printf '#!/usr/bin/env python3\nimport sys\nraise SystemExit(0)\n' >"$TMP/trapped-cutover.py"
chmod +x "$TMP/trapped-launch.sh" "$TMP/trapped-cutover.py"
: >"$TRAP_LOG"
trap_head_before="$(git -C "$TRAP_GLOBAL" rev-parse HEAD)"
set +e
trap_out="$(
  unset SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE
  SOLAR_RUNTIME_ROOT="$TRAP_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/trapped-launch.sh" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$TRAP_GLOBAL/core/skills/solar-client/scripts/client_update.sh" \
    --workspace "$TRAP_WS" --ref v0.0.2 --yes 2>&1
)"
trap_ec=$?
set -e
assert_ok "old portable updater exits non-zero" test "$trap_ec" -ne 0
assert_ok "old portable updater treats the bundle as the install" grep -q 'mode=bundle-core' <<<"$trap_out"
trap_bundle_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$TRAP_WS/.solar/bundle")"
assert_ok "old portable updater names the bundle" grep -q "SOLAR_ROOT=$trap_bundle_abs" <<<"$trap_out"
assert_ok "old portable updater does not move the global install" \
  bash -c 'test "$(git -C "$1" rev-parse HEAD)" = "$2"' _ "$TRAP_GLOBAL" "$trap_head_before"
assert_ok "old portable updater leaves the global marker" grep -qx 'OLD' "$TRAP_GLOBAL/core/.trapped-marker"
assert_ok "old portable updater does not bootout launchctl" test ! -s "$TRAP_LOG"
[[ "$trap_ec" -ne 0 ]] || echo "$trap_out" >&2

# The operator escape: checkout the fix in the global install, then bundle create, then update.
git -C "$TRAP_GLOBAL" checkout -q v0.0.2
assert_ok "checkout of the fix lands in the global install" grep -qx 'NEW' "$TRAP_GLOBAL/core/.trapped-marker"
set +e
trap_bundle_out="$(
  cd "$TRAP_WS"
  unset SOLAR_ROOT SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE
  bash "$TRAP_GLOBAL/core/skills/solar-client/scripts/client_bundle.sh" create 2>&1
)"
trap_bundle_ec=$?
set -e
assert_ok "bundle create after the checkout exits 0" test "$trap_bundle_ec" -eq 0
assert_ok "bundle create after the checkout includes solar-state" \
  test -f "$TRAP_WS/.solar/bundle/core/skills/solar-state/scripts/solar_state_cutover.py"
[[ "$trap_bundle_ec" -eq 0 ]] || echo "$trap_bundle_out" >&2
: >"$TRAP_LOG"
set +e
trap_new_out="$(
  unset SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE
  SOLAR_RUNTIME_ROOT="$TRAP_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_CUTOVER_SCRIPT="$TMP/trapped-cutover.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/trapped-launch.sh" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$TRAP_GLOBAL/core/skills/solar-client/scripts/client_update.sh" \
    --workspace "$TRAP_WS" --ref v0.0.2 --yes 2>&1
)"
trap_new_ec=$?
set -e
trap_global_abs="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$TRAP_GLOBAL")"
assert_ok "update after the checkout exits 0" test "$trap_new_ec" -eq 0
assert_ok "update after the checkout uses the global install" grep -q "SOLAR_ROOT=$trap_global_abs" <<<"$trap_new_out"
assert_ok "update after the checkout uses git-repo mode" grep -q 'mode=git-repo' <<<"$trap_new_out"
assert_ok "update after the checkout does not treat the bundle as the install" \
  bash -c '! grep -q mode=bundle-core <<<"$1"' _ "$trap_new_out"
assert_ok "update after the checkout does not bootout launchctl" test ! -s "$TRAP_LOG"
[[ "$trap_new_ec" -eq 0 ]] || echo "$trap_new_out" >&2
fi

# --- a clean git install reports rollback; a dirty one reports uncommitted changes ---
# Runs under the shell_runtime_guard sourced above.
MSG_WS="$TMP/msg-ws"
MSG_INSTALL="$TMP/msg-install"
MSG_RT="$TMP/msg-runtime"
mkdir -p "$MSG_WS/sun" "$MSG_WS/.solar" "$MSG_RT" \
  "$MSG_INSTALL/core/skills/solar-client/scripts"
printf '%s\n' '#!/usr/bin/env bash' 'echo solar' \
  >"$MSG_INSTALL/core/skills/solar-client/scripts/solar"
chmod +x "$MSG_INSTALL/core/skills/solar-client/scripts/solar"
printf '%s\n' '{"layout":"solar-client-v1.2","scope":"workspace","core_source":"global","core_version":"v0","requires_global_client":true}' \
  >"$MSG_WS/.solar/settings.json"
printf '%s\n' 'clean' >"$MSG_INSTALL/README"
git -C "$MSG_INSTALL" init -q
git -C "$MSG_INSTALL" config user.email "test@test"
git -C "$MSG_INSTALL" config user.name "Test"
git -C "$MSG_INSTALL" add -A && git -C "$MSG_INSTALL" commit -q -m "init"
git -C "$MSG_INSTALL" tag v0.0.1
set +e
clean_msg="$(
  unset SOLAR_WORKSPACE SOLAR_CORE_SOURCE SOLAR_GLOBAL_ROOT SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE
  unset SOLAR_CLIENT_CUTOVER_SCRIPT SOLAR_CLIENT_CUTOVER_ROOT
  SOLAR_ROOT="$MSG_INSTALL" \
  SOLAR_RUNTIME_ROOT="$MSG_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$UPDATE_SCRIPT" --workspace "$MSG_WS" --ref v0.0.1 --yes 2>&1
)"
set -e
assert_ok "clean git install reports the rollback checkout" grep -q 'rollback: git -C' <<<"$clean_msg"
assert_ok "clean git install does not report uncommitted changes" \
  bash -c '! grep -q "uncommitted changes" <<<"$1"' _ "$clean_msg"
printf '%s\n' 'dirty' >>"$MSG_INSTALL/README"
set +e
dirty_msg="$(
  unset SOLAR_WORKSPACE SOLAR_CORE_SOURCE SOLAR_GLOBAL_ROOT SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE
  unset SOLAR_CLIENT_CUTOVER_SCRIPT SOLAR_CLIENT_CUTOVER_ROOT
  SOLAR_ROOT="$MSG_INSTALL" \
  SOLAR_RUNTIME_ROOT="$MSG_RT" \
  SOLAR_CLIENT_STATE_PY="$CORE_ROOT/skills/solar-state/scripts/solar_state.py" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl" \
  SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE=ok \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  bash "$UPDATE_SCRIPT" --workspace "$MSG_WS" --ref v0.0.1 --yes 2>&1
)"
set -e
assert_ok "dirty git install reports uncommitted changes" grep -q 'uncommitted changes' <<<"$dirty_msg"
assert_ok "dirty git install does not report the rollback checkout" \
  bash -c '! grep -q "rollback: git -C" <<<"$1"' _ "$dirty_msg"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
