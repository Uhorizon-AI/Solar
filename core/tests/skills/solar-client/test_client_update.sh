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
# Directory not writable → atomic .env rewrite fails; update must abort pre-apply
chmod a-w "$WS_MIG"
set +e
mig_out="$(bash "$UPDATE_SCRIPT" --workspace "$WS_MIG" --yes 2>&1)"
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

# --- first update from the published updater, which never calls the cutover ---
# v1 is HEAD's client_update.sh: it reloads the new client_lib and restarts.
# The new restart migrates before it starts anything.
WS_UP="$TMP/ws-up"
INSTALL_UP="$WS_UP/solar"
UP_LIB="$INSTALL_UP/core/skills/solar-client/scripts/client_lib.sh"
UP_UPDATE="$INSTALL_UP/core/skills/solar-client/scripts/client_update.sh"
REPO_ROOT="$(cd "$CORE_ROOT/.." && pwd)"
mkdir -p "$WS_UP/sun" "$WS_UP/.solar" "$INSTALL_UP/core/skills"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"v0.0.1","core_commit":"unknown","core_source":"global"}' >"$WS_UP/.solar/settings.json"
cp -R "$CORE_ROOT/skills/solar-client" "$INSTALL_UP/core/skills/"
cp -R "$CORE_ROOT/skills/solar-paths" "$INSTALL_UP/core/skills/"
rm -rf "$INSTALL_UP/core/skills/solar-client/scripts/__pycache__"
rm -rf "$INSTALL_UP/core/skills/solar-paths/scripts/__pycache__"
git -C "$REPO_ROOT" show HEAD:core/skills/solar-client/scripts/client_update.sh >"$UP_UPDATE"
git -C "$REPO_ROOT" show HEAD:core/skills/solar-client/scripts/client_lib.sh >"$UP_LIB"
assert_ok "published updater does not call the cutover" \
  bash -c '! grep -q solar_client_state_cutover "$1"' _ "$UP_UPDATE"
git -C "$INSTALL_UP" init -q
git -C "$INSTALL_UP" config user.email "test@test"
git -C "$INSTALL_UP" config user.name "Test"
git -C "$INSTALL_UP" add -A && git -C "$INSTALL_UP" commit -q -m "v1" && git -C "$INSTALL_UP" tag v0.0.1
cp "$UPDATE_SCRIPT" "$UP_UPDATE"
cp "$CORE_ROOT/skills/solar-client/scripts/client_lib.sh" "$UP_LIB"
git -C "$INSTALL_UP" add -A && git -C "$INSTALL_UP" commit -q -m "v2" && git -C "$INSTALL_UP" tag v0.0.2
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

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
