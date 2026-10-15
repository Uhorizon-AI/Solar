#!/usr/bin/env bash
# The console port is no longer written to .env. The doctor must assume 9000 when
# SOLAR_APP_PORT is unset, must not abort (set -e) in any of its port checks, and must
# report what it finds. lsof is a test double: nothing here touches a real port.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPTS="$ROOT/skills/solar-client/scripts"
TMP="$(mktemp -d)"
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null || true; done
  rm -rf "$TMP"
}
trap cleanup EXIT
unset SOLAR_APP_PORT SOLAR_HTTP_PORT
export SOLAR_APP_DATA="$TMP/appdata" SOLAR_RUNTIME_ROOT="$TMP/runtime"
mkdir -p "$TMP/bin"
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS + 1)); }
pass() { echo "PASS: $1"; }

# lsof double: logs the queried port and answers with the pid in $FAKE_LSOF_PID, if any.
cat >"$TMP/bin/lsof" <<'DOUBLE'
#!/bin/bash
for a in "$@"; do case "$a" in tcp:*) echo "${a#tcp:}" >>"$FAKE_LSOF_LOG" ;; esac; done
[[ -n "${FAKE_LSOF_PID:-}" ]] && echo "$FAKE_LSOF_PID"
exit 0
DOUBLE
chmod +x "$TMP/bin/lsof"
export FAKE_LSOF_LOG="$TMP/lsof.log"
# curl double: the doctor's health fallback must never reach a real console on 9000.
printf '#!/bin/bash\nexit 22\n' >"$TMP/bin/curl"
chmod +x "$TMP/bin/curl"

# Runs the verbose check of client_doctor.sh under set -euo pipefail. The function is
# extracted with awk (portable to BSD and GNU) and the result is returned, never inferred.
run_verbose_check() {
  PATH="$TMP/bin:$PATH" bash -c '
    set -euo pipefail
    ok() { echo "OK: $1"; }; warn() { echo "WARN: $1"; }
    source "$1/client_lib.sh"
    source "$1/client_doctor_lib.sh"
    body="$(awk "/^_port_check_verbose\\(\\) \\{/,/^\\}/" "$1/client_doctor.sh")"
    [[ -n "$body" ]] || { echo "EXTRACTION-FAILED"; exit 99; }
    eval "$body"
    _port_check_verbose SOLAR_APP_PORT
    _port_check_verbose SOLAR_HTTP_PORT
    echo reached-end
  ' _ "$SCRIPTS" 2>&1
}

# 1. Unset key, no listener: does not abort, and asks about 9000 (not about nothing).
: >"$FAKE_LSOF_LOG"
unset FAKE_LSOF_PID
out="$(run_verbose_check)" || { fail "aborted with the key unset: $out"; out=""; }
grep -q reached-end <<<"$out" && pass "survives an unset SOLAR_APP_PORT with no listener" || fail "did not reach the end: $out"
grep -qx 9000 "$FAKE_LSOF_LOG" && pass "assumes 9000 when the key is unset" || fail "never asked about 9000: $(cat "$FAKE_LSOF_LOG")"

# 2. A host_server.py on the console port is reported as Solar App.
cp "$(command -v python3)" "$TMP/py" 2>/dev/null || ln -s "$(command -v python3)" "$TMP/py"
printf 'import time\ntime.sleep(60)\n' >"$TMP/host_server.py"
"$TMP/py" "$TMP/host_server.py" & PIDS+=("$!")
export FAKE_LSOF_PID="${PIDS[0]}"
sleep 0.3
out="$(run_verbose_check)" || fail "aborted with a Solar console listening: $out"
grep -q 'OK: SOLAR_APP_PORT=9000 in use by Solar App' <<<"$out" && pass "reports a console on the default port" || fail "no OK line: $out"

# 3. Any other process on the console port is a warning, not an abort.
sleep 60 & PIDS+=("$!")
export FAKE_LSOF_PID="${PIDS[1]}"
out="$(run_verbose_check)" || fail "aborted with a foreign process listening: $out"
grep -q 'WARN: SOLAR_APP_PORT=9000 is in use by a non-Solar process' <<<"$out" && pass "warns about a foreign process" || fail "no WARN line: $out"
grep -q reached-end <<<"$out" && pass "keeps going after a warning" || fail "stopped after the warning: $out"

# 4. The same default applies in solar_client_check_ports (used by solar status).
out="$(PATH="$TMP/bin:$PATH" bash -c '
  set -euo pipefail
  source "$1/client_lib.sh"; source "$1/client_doctor_lib.sh"
  status=0; solar_client_check_ports || status=$?
  echo "status=$status msg=$SOLAR_CLIENT_PORTS_MSG"
' _ "$SCRIPTS" 2>&1)" || fail "solar_client_check_ports aborted: $out"
grep -q 'status=1 msg=SOLAR_APP_PORT=9000 foreign pid' <<<"$out" && pass "status check flags the foreign process on 9000" || fail "unexpected status output: $out"

echo "failures: $FAILS"
[[ "$FAILS" -eq 0 ]]
