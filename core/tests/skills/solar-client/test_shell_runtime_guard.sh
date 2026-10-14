#!/usr/bin/env bash
# The shell-test guard aborts before a test can touch the live runtime.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
GUARD="$CORE_ROOT/tests/support/shell_runtime_guard.sh"
PASS=0
FAIL=0

assert_eq() {
  local label="$1" got="$2" want="$3"
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
mkdir -p "$TMP/runtime"
cat >"$TMP/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/launchctl"

set +e
env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA -u SOLAR_CLIENT_LAUNCHCTL \
  bash -c 'source "$1"; solar_test_guard' _ "$GUARD" >/dev/null 2>"$TMP/live.err"
live_ec=$?
env -u SOLAR_APP_DATA \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="/bin/launchctl" \
  bash -c 'source "$1"; solar_test_guard' _ "$GUARD" >/dev/null 2>"$TMP/bin.err"
bin_ec=$?
LIVE="$(env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA python3 "$CORE_ROOT/skills/solar-paths/scripts/solar_runtime.py" runtime)"
env -u SOLAR_APP_DATA \
  SOLAR_RUNTIME_ROOT="$LIVE" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard' _ "$GUARD" >/dev/null 2>"$TMP/path.err"
live_path_ec=$?
env -u SOLAR_APP_DATA \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard' _ "$GUARD" >/dev/null 2>"$TMP/ok.err"
ok_ec=$?
env -u SOLAR_RUNTIME_ROOT \
  SOLAR_APP_DATA="$TMP/app-data" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard' _ "$GUARD" >/dev/null 2>"$TMP/app.err"
app_ec=$?
set -e

assert_eq "unset runtime aborts" "$live_ec" "97"
assert_eq "unset runtime names the live runtime" "$(grep -c 'live Solar runtime' "$TMP/live.err")" "1"
assert_eq "system launchctl aborts" "$bin_ec" "97"
assert_eq "system launchctl is named" "$(grep -c 'system binary' "$TMP/bin.err")" "1"
assert_eq "runtime pointed at the solar-paths default aborts" "$live_path_ec" "97"
assert_eq "temp runtime and a test double pass" "$ok_ec" "0"
assert_eq "SOLAR_APP_DATA away from home passes" "$app_ec" "0"

# --- Opt-in --services check (state-cutover containment) --------------------
# Two fixture installs, so the realpath comparison runs without touching any
# real install: a validated root only needs core/skills/solar-client/scripts/solar.
mkdir -p "$TMP/install/core/skills/solar-client/scripts" "$TMP/other/core/skills/solar-client/scripts"
: >"$TMP/install/core/skills/solar-client/scripts/solar"
: >"$TMP/other/core/skills/solar-client/scripts/solar"
chmod +x "$TMP/install/core/skills/solar-client/scripts/solar" "$TMP/other/core/skills/solar-client/scripts/solar"

guard_services() {
  env -u SOLAR_APP_DATA -u SOLAR_GLOBAL_ROOT -u SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE \
    -u SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE -u SOLAR_CLIENT_PS_OUTPUT_FILE "$@"
}

set +e
guard_services \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --services' _ "$GUARD" >/dev/null 2>"$TMP/services-live.err"
services_live_ec=$?
guard_services \
  SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --services' _ "$GUARD" >/dev/null 2>"$TMP/services-none.err"
services_none_ec=$?
guard_services \
  SOLAR_CLIENT_PS_OUTPUT_FILE="$TMP/ps.txt" \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --services' _ "$GUARD" >/dev/null 2>"$TMP/services-ps.err"
services_ps_ec=$?
guard_services \
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$TMP/other" \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --services' _ "$GUARD" >/dev/null 2>"$TMP/services-other.err"
services_other_ec=$?
guard_services \
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$TMP/install" \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --services' _ "$GUARD" >/dev/null 2>"$TMP/services-pinned.err"
services_pinned_ec=$?
guard_services \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard' _ "$GUARD" >/dev/null 2>"$TMP/noflag.err"
noflag_ec=$?
guard_services \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --bogus' _ "$GUARD" >/dev/null 2>"$TMP/bogus.err"
bogus_ec=$?
set -e

assert_eq "--services on the resolved global install aborts" "$services_live_ec" "97"
assert_eq "--services names the live global install" "$(grep -c 'live global install' "$TMP/services-live.err")" "1"
assert_eq "--services with the service override passes" "$services_none_ec" "0"
assert_eq "--services with a PS output file passes" "$services_ps_ec" "0"
assert_eq "--services on an install other than the pinned global passes" "$services_other_ec" "0"
assert_eq "--services when the override pins the global at the same install aborts" "$services_pinned_ec" "97"
assert_eq "no flag leaves the effective-equals-global case untouched" "$noflag_ec" "0"
assert_eq "unknown guard option aborts" "$bogus_ec" "97"
assert_eq "unknown guard option is named" "$(grep -c 'unknown solar_test_guard option' "$TMP/bogus.err")" "1"

# The guard and solar_host_runtime_is_temporary duplicate the "temporary runtime"
# rule by hand. Pin them together: the same environment must get the same answer
# from both, or SOLAR_APP_PORT_OVERRIDE could be honoured on a real install.
HOST_LIB="$CORE_ROOT/skills/solar-app/scripts/host_lib.sh"
host_temp() {
  env -u SOLAR_GLOBAL_ROOT "$@" \
    bash -c 'source "$1"; solar_host_load_env; solar_host_runtime_is_temporary && echo yes || echo no' \
    _ "$HOST_LIB"
}
guard_verdict() {
  # 0 from the guard means the runtime is temporary (compare == distinct).
  env -u SOLAR_GLOBAL_ROOT "$@" \
    bash -c 'source "$1"; live="$(solar_test_live_runtime)"; resolved="$(solar_test_resolved_runtime)";
      l="$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$live")";
      r="$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$resolved")";
      [[ "$r" != "$l" ]] && echo yes || echo no' \
    _ "$GUARD"
}
set +e
temp_env_temp="$(host_temp SOLAR_RUNTIME_ROOT="$TMP/runtime")"
temp_guard_temp="$(guard_verdict SOLAR_RUNTIME_ROOT="$TMP/runtime")"
LIVE_RT="$(env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA python3 "$CORE_ROOT/skills/solar-paths/scripts/solar_runtime.py" runtime)"
temp_env_live="$(host_temp SOLAR_RUNTIME_ROOT="$LIVE_RT")"
temp_guard_live="$(guard_verdict SOLAR_RUNTIME_ROOT="$LIVE_RT")"
set -e
assert_eq "temporary runtime agrees between host_lib and the guard" "$temp_env_temp" "$temp_guard_temp"
assert_eq "live runtime agrees between host_lib and the guard" "$temp_env_live" "$temp_guard_live"
assert_eq "a temp runtime reads as temporary in both" "$temp_env_temp" "yes"
assert_eq "the live runtime reads as not temporary in both" "$temp_env_live" "no"

# The service check must not fail open silently: an unresolvable global install
# is an abort with a reason, never a silent pass. The guard is mirrored so its
# relative paths land on a stub that refuses to resolve the global install.
mkdir -p "$TMP/mirror/tests/support" "$TMP/mirror/skills/solar-paths/scripts"
cp "$GUARD" "$TMP/mirror/tests/support/guard.sh"
cp "$(dirname "$GUARD")/../../skills/solar-paths/scripts/solar_runtime.py" \
  "$TMP/mirror/skills/solar-paths/scripts/solar_runtime.py"
cat >"$TMP/mirror/skills/solar-paths/scripts/resolve_solar_paths.sh" <<'EOF'
#!/usr/bin/env bash
solar_global_install_root() { return 1; }
EOF
set +e
guard_services \
  SOLAR_ROOT="$TMP/install" \
  SOLAR_RUNTIME_ROOT="$TMP/runtime" \
  SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl" \
  bash -c 'source "$1"; solar_test_guard --services' _ "$TMP/mirror/tests/support/guard.sh" \
  >/dev/null 2>"$TMP/services-failopen.err"
services_failopen_ec=$?
set -e
assert_eq "an unresolvable global install aborts instead of failing open" "$services_failopen_ec" "97"
assert_eq "the fail-open abort is named" "$(grep -c 'could not resolve the Client' "$TMP/services-failopen.err")" "1"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
