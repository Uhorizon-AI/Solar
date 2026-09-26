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

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
