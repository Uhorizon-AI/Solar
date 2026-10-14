#!/usr/bin/env bash
# test_host_identity.sh — console identity is verified before reuse; a console
# of another workspace or runtime is rejected and never stopped.
#
# Fully isolated: temporary workspace, runtime, app data and PATH doubles. The
# stub console binds 127.0.0.1:0 and SOLAR_APP_PORT_OVERRIDE keeps it away from
# the real 9000. Nothing here starts, stops or probes the machine's console.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
HOST_LIB="$SCRIPTS/host_lib.sh"
REAL_PYTHON="$(python3 -c 'import os,sys; print(os.path.realpath(sys.executable))')"
PASS=0
FAIL=0

TMP="$(mktemp -d)"
STUB_PID=""
STUB_PORT=""
# Record the machine's real console listeners on 9000 before any stub runs, so a
# later assert can prove the suite never touched them.
REAL_9000_BEFORE="$(/usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
cleanup() {
  if [[ -n "$STUB_PID" ]] && kill -0 "$STUB_PID" 2>/dev/null; then
    kill "$STUB_PID" 2>/dev/null || true
    wait "$STUB_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

# --- Islands of isolation ---------------------------------------------------
export SOLAR_ROOT="$CORE_ROOT/.."
[[ -d "${SOLAR_ROOT}/core" ]] || export SOLAR_ROOT="$CORE_ROOT"
export SOLAR_APP_DATA="$TMP/appdata"
export SOLAR_RUNTIME_ROOT="$TMP/runtime"
export SOLAR_WORKSPACE="$TMP/ws"
export SOLAR_HOST_RUNTIME_DIR="$TMP/hostruntime"
mkdir -p "$SOLAR_APP_DATA" "$SOLAR_RUNTIME_ROOT" "$SOLAR_HOST_RUNTIME_DIR" \
  "$SOLAR_WORKSPACE/sun" "$SOLAR_WORKSPACE/.solar" "$TMP/bin" "$TMP/home/Library/LaunchAgents"
echo '{"layout":"solar-client-v1.2","core_source":"global"}' >"$SOLAR_WORKSPACE/.solar/settings.json"
: >"$SOLAR_WORKSPACE/.env"
# solar_resolve_paths requires the cwd to be inside the workspace it resolves.
cd "$SOLAR_WORKSPACE"

# launchctl double: the guard and any agent step must never reach the real one.
cat >"$TMP/bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/bin/launchctl"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/bin/launchctl"

# --- Stub console -----------------------------------------------------------
# Small python3 server: /health serves a configurable JSON payload, /app an HTML
# page with id="health", /api/runtime/health a fresh healthy payload. It binds
# an ephemeral loopback port, writes the chosen port to a file and exits on
# SIGTERM.
cat >"$TMP/stub.py" <<'PY'
import http.server, json, signal, sys
from datetime import datetime, timezone
identity_path, port_path = sys.argv[1], sys.argv[2]

def stop(signum, frame):
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def identity():
    try:
        with open(identity_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            payload = {"service": "solar-console", "status": "available", "process_ok": True}
            payload.update(identity())
            self._json(payload)
        elif self.path == "/app":
            body = b'<html><body><div id="health"></div></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/runtime/health"):
            self._json({"service": "solar-console", "storage_ok": True, "status": "healthy",
                        "checked_at": datetime.now(timezone.utc).isoformat()})
        else:
            self._json({"error": "Not found"}, 404)

server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(port_path, "w", encoding="utf-8") as fh:
    fh.write(str(server.server_address[1]))
try:
    server.serve_forever()
finally:
    server.server_close()
PY

start_stub() {
  local name="$1"
  local ident="$TMP/$name.identity.json"
  local portfile="$TMP/$name.port"
  printf '%s' "${2:-{\}}" >"$ident"
  : >"$portfile"
  # Launch detached from this shell's stdout/stderr: a background server that
  # inherits a command-substitution pipe would keep that pipe open forever.
  "$REAL_PYTHON" "$TMP/stub.py" "$ident" "$portfile" >/dev/null 2>&1 &
  STUB_PID=$!
  local port=""
  local _i
  for _i in $(seq 1 50); do
    port="$(cat "$portfile" 2>/dev/null || true)"
    [[ -n "$port" ]] && break
    sleep 0.1
  done
  [[ -n "$port" ]] || { echo "FATAL: stub $name did not report a port" >&2; exit 1; }
  # Set for the whole test, not just this command substitution.
  SOLAR_APP_PORT_OVERRIDE="$port"
  export SOLAR_APP_PORT_OVERRIDE
  STUB_PORT="$port"
}

stop_stub() {
  if [[ -n "$STUB_PID" ]] && kill -0 "$STUB_PID" 2>/dev/null; then
    kill "$STUB_PID" 2>/dev/null || true
    wait "$STUB_PID" 2>/dev/null || true
  fi
  STUB_PID=""
  # The stub releases the port asynchronously; wait for the port to be free so a
  # following start does not race with the previous listener.
  local _i
  for _i in $(seq 1 25); do
    [[ -z "$STUB_PORT" ]] && break
    /usr/sbin/lsof -nP -iTCP:"$STUB_PORT" -sTCP:LISTEN -t >/dev/null 2>&1 || break
    sleep 0.2
  done
}

# Wait until a pid is really gone (kill -0 fails), up to ~2s.
wait_gone() {
  local pid="$1"
  local _i
  for _i in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.1
  done
  return 1
}

liveness() { bash "$SCRIPTS/check_host.sh" --liveness >"$TMP/live.err" 2>&1; }
full_check() { bash "$SCRIPTS/check_host.sh" >"$TMP/full.err" 2>&1; }

# --- 1. Matching identity ---------------------------------------------------
start_stub match "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
set +e
liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "matching identity passes --liveness" \
  || { fail "matching identity passes --liveness (ec=$ec)"; cat "$TMP/live.err" >&2; }
stop_stub

# --- 2. Another workspace ---------------------------------------------------
start_stub otherws "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
set +e
liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "another workspace is rejected" || fail "another workspace is rejected (ec=$ec)"
grep -q "$TMP/another-workspace" "$TMP/live.err" && pass "diagnosis names the other workspace" \
  || { fail "diagnosis names the other workspace"; cat "$TMP/live.err" >&2; }
stop_stub

# --- 3. Another runtime -----------------------------------------------------
start_stub otherrt "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$TMP/another-runtime\"}"
set +e
liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "another runtime is rejected" || fail "another runtime is rejected (ec=$ec)"
stop_stub

# --- 4. Symlink-equivalent identity ----------------------------------------
# The console reports the physical path; this runtime is reached through a
# symlink. Both must resolve to the same console.
ln -sfn "$SOLAR_WORKSPACE" "$TMP/ws-link"
REAL_WS="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SOLAR_WORKSPACE")"
start_stub symlink "{\"workspace\":\"$REAL_WS\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
set +e
SOLAR_WORKSPACE="$TMP/ws-link" liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "symlink-equivalent identity passes" \
  || { fail "symlink-equivalent identity passes (ec=$ec)"; cat "$TMP/live.err" >&2; }
stop_stub

# --- 5. Legacy health with no identity, adopted via own pid file ------------
# The stub serves no workspace/runtime. A ps double makes this runtime's pid
# file name a live host_server.py. os.kill(pid, 0) needs the pid to exist and be
# ours, so a safe local process (this shell's own child) stands in for the
# "live host_server.py" the pid file points at. Nothing here can signal a
# foreign process.
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "python3 host_server.py"\n' >"$TMP/bin/ps"
chmod +x "$TMP/bin/ps"
ln -sfn "$REAL_PYTHON" "$TMP/bin/python3-real"
cat >"$TMP/bin/python3" <<'EOF'
#!/usr/bin/env bash
exec "$(dirname "${BASH_SOURCE[0]}")/python3-real" "$@"
EOF
chmod +x "$TMP/bin/python3"
start_stub legacy-own "{}"
# The pid file names the listener itself: that is the proof of ownership the
# identity policy accepts (a pid file of a different process proves nothing).
printf '%s\n' "$STUB_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "identity-less console with this runtime's pid file is adopted" \
  || { fail "identity-less console with this runtime's pid file is adopted (ec=$ec)"; cat "$TMP/live.err" >&2; }
stop_stub

# --- 6. Legacy health with no identity and no pid file ----------------------
rm -f "$SOLAR_HOST_RUNTIME_DIR/host.pid"
start_stub legacy-orphan "{}"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "identity-less console without a pid file is rejected" \
  || fail "identity-less console without a pid file is rejected (ec=$ec)"
grep -q "no identity and no process of this runtime" "$TMP/live.err" \
  && pass "diagnosis explains the missing identity and pid file" \
  || { fail "diagnosis explains the missing identity and pid file"; cat "$TMP/live.err" >&2; }
stop_stub

# --- 7. No-flag mode also enforces identity (supervisor path) ---------------
start_stub supervise "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
set +e
full_check
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "no-flag check rejects another workspace" \
  || fail "no-flag check rejects another workspace (ec=$ec)"
grep -q "console identity mismatch" "$TMP/full.err" \
  && pass "no-flag diagnosis names the identity mismatch" \
  || { fail "no-flag diagnosis names the identity mismatch"; cat "$TMP/full.err" >&2; }
stop_stub

# --- 7b. --json without identity is unavailable, not partial ----------------
# The fail-open guard for JSON: a mismatch must set available=false with an
# error that names the identity, never report the console as usable.
start_stub json-other "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
set +e
JSON_OUT="$(bash "$SCRIPTS/check_host.sh" --json 2>&1)"
json_ec=$?
set -e
[[ "$json_ec" -ne 0 ]] && pass "--json without identity exits non-zero" \
  || fail "--json without identity exits non-zero (ec=$json_ec)"
python3 - "$JSON_OUT" <<'PY' && pass "--json reports available:false with an identity error" \
  || { fail "--json reports available:false with an identity error"; echo "$JSON_OUT" >&2; }
import json, sys
data = json.loads(sys.argv[1])
ok = data.get("available") is False and str(data.get("error", "")).startswith("console identity mismatch")
raise SystemExit(0 if ok else 1)
PY
stop_stub

# --- 8. solar_host_stop_orphan_listeners never kills a foreign console ------
# A lsof double names the listener; a ps double makes it look like
# host_server.py; the stub on the chosen port decides the identity.
lsof_double() {
  cat >"$TMP/bin/lsof" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${FAKE_LSOF_PID:-999999}"
EOF
  chmod +x "$TMP/bin/lsof"
}
lsof_double
STOP_LIB_ERR="$TMP/stop-lib.err"
run_stop() {
  set +e
  PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" FAKE_LSOF_PID="$1" \
    bash -c 'source "$1"; solar_host_stop_orphan_listeners' _ "$HOST_LIB" >/dev/null 2>"$STOP_LIB_ERR"
  STOP_EC=$?
  set -e
}
# (a) A listener that looks like host_server.py but whose identity is foreign:
# report, return 2, never kill.
start_stub foreign-stop "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
run_stop 777777
[[ "$STOP_EC" -eq 2 ]] && pass "foreign listener returns 2" || fail "foreign listener returns 2 (ec=$STOP_EC)"
grep -q "WARN: stopping orphan" "$STOP_LIB_ERR" && fail "foreign listener was told to stop" \
  || pass "foreign listener was never told to stop"
grep -q "kill 777777" "$STOP_LIB_ERR" && pass "diagnosis names the manual command" \
  || { fail "diagnosis names the manual command"; cat "$STOP_LIB_ERR" >&2; }
stop_stub
# (b) A listener that is this runtime's own console is stopped (return 0), and
# the process is really gone afterwards.
start_stub own-stop "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
OWN_PID="$STUB_PID"
run_stop "$OWN_PID"
[[ "$STOP_EC" -eq 0 ]] && pass "own console listener is stopped (return 0)" \
  || fail "own console listener is stopped (return 0) (ec=$STOP_EC)"
set +e
kill -0 "$OWN_PID" 2>/dev/null
own_alive=$?
set -e
[[ "$own_alive" -ne 0 ]] && pass "own console listener is really stopped" \
  || fail "own console listener is really stopped (pid $OWN_PID still alive)"
stop_stub
# (c) An own console that is hung: no /health answer, no pid file, but this
# install's host_server.py in its command line. It must be recognised as ours
# and stopped, never abandoned as foreign.
sleep 120 & disown 2>/dev/null || true
HUNG_PID=$!
cat >"$TMP/bin/ps" <<EOF
#!/usr/bin/env bash
printf '%s\n' "python3 $CORE_ROOT/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
run_stop "$HUNG_PID"
[[ "$STOP_EC" -eq 0 ]] && pass "own hung console is stopped (return 0)" \
  || fail "own hung console is stopped (return 0) (ec=$STOP_EC)"
kill -0 "$HUNG_PID" 2>/dev/null && fail "own hung console was left running" \
  || pass "own hung console was really stopped"
kill "$HUNG_PID" 2>/dev/null || true
wait "$HUNG_PID" 2>/dev/null || true
# (c2) The same hung own console, launched with the macOS capital-P interpreter
# (Python.app): it must still be recognised as ours.
sleep 120 & disown 2>/dev/null || true
HUNG_CAP_PID=$!
cat >"$TMP/bin/ps" <<EOF
#!/usr/bin/env bash
printf '%s\n' "Python -u $CORE_ROOT/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
run_stop "$HUNG_CAP_PID"
[[ "$STOP_EC" -eq 0 ]] && pass "own hung console under macOS Python is stopped (return 0)" \
  || fail "own hung console under macOS Python is stopped (return 0) (ec=$STOP_EC)"
kill -0 "$HUNG_CAP_PID" 2>/dev/null && fail "own hung console under macOS Python was left running" \
  || pass "own hung console under macOS Python was really stopped"
kill "$HUNG_CAP_PID" 2>/dev/null || true
wait "$HUNG_CAP_PID" 2>/dev/null || true
# (d) A hung console of another install stays foreign: report, never kill.
sleep 120 & disown 2>/dev/null || true
FOREIGN_HUNG_PID=$!
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 /somewhere/else/core/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
run_stop "$FOREIGN_HUNG_PID"
[[ "$STOP_EC" -eq 2 ]] && pass "hung console of another install returns 2" \
  || fail "hung console of another install returns 2 (ec=$STOP_EC)"
kill -0 "$FOREIGN_HUNG_PID" 2>/dev/null && pass "hung console of another install was left running" \
  || fail "hung console of another install was left running"
kill "$FOREIGN_HUNG_PID" 2>/dev/null || true
wait "$FOREIGN_HUNG_PID" 2>/dev/null || true
# (e) Ours by identity but not host_server.py: it must not be killed, and the
# caller must learn the port is still held (return 4, not 0/1) so it never says
# "not running" while the port is busy.
start_stub own-not-server "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 algo-que-no-es-el-server.py"
EOF
chmod +x "$TMP/bin/ps"
run_stop "$STUB_PID"
[[ "$STOP_EC" -eq 4 ]] && pass "own listener that is not host_server.py returns 4" \
  || fail "own listener that is not host_server.py returns 4 (ec=$STOP_EC)"
grep -q "ours by identity but is not host_server.py" "$STOP_LIB_ERR" \
  && pass "the non-stoppable own listener is named" \
  || { fail "the non-stoppable own listener is named"; cat "$STOP_LIB_ERR" >&2; }
kill -0 "$STUB_PID" 2>/dev/null && pass "the non-stoppable own listener was left running" \
  || fail "the non-stoppable own listener was left running"
stop_stub
# Drop the ps and lsof doubles: later sections must see the real commands.
rm -f "$TMP/bin/ps" "$TMP/bin/lsof"

# --- 9. No residue: the stub port has no listener after the stub stops ------
start_stub residue "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
before="$(/usr/sbin/lsof -nP -iTCP:"$STUB_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
[[ -n "$before" ]] && pass "stub held the port while running" || fail "stub held the port while running"
stop_stub
after="$(/usr/sbin/lsof -nP -iTCP:"$STUB_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
[[ -z "$after" ]] && pass "no new listener left on the stub port" \
  || fail "no new listener left on the stub port (pids=$after)"

# --- 10. Partial identity needs a proof ------------------------------------
# A console that reports only the runtime must not be adopted on its own.
start_stub partial "{\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
# A ps double makes the stub's pid look like a live host_server.py, which is what
# the pid file has to prove.
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 host_server.py"
EOF
chmod +x "$TMP/bin/ps"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "partial identity without a proof is rejected" \
  || fail "partial identity without a proof is rejected (ec=$ec)"
grep -q "partial identity" "$TMP/live.err" && pass "diagnosis says the identity is partial" \
  || { fail "diagnosis says the identity is partial"; cat "$TMP/live.err" >&2; }
# The same console is adopted once this runtime's own pid file proves the process.
# The pid file must name the listener itself: a pid file of another process
# proves nothing about who is on the port.
printf '%s\n' "$STUB_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "partial identity with this runtime's pid file is adopted" \
  || { fail "partial identity with this runtime's pid file is adopted (ec=$ec)"; cat "$TMP/live.err" >&2; }
rm -f "$SOLAR_HOST_RUNTIME_DIR/host.pid"
# A console that reports only the workspace is refused the same way.
cat >"$TMP/partial.identity.json" <<EOF
{"workspace":"$SOLAR_WORKSPACE"}
EOF
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "workspace-only identity without a proof is rejected" \
  || fail "workspace-only identity without a proof is rejected (ec=$ec)"
stop_stub
# Drop the ps double: sections 11 and later install their own.
rm -f "$TMP/bin/ps"

# --- 11. Legacy console of this install is recovered, not stranded ---------
# After solar client update the console may still run the code from before
# /health reported a runtime, with no pid file. Its command line names this
# install's host_server.py, which is a proof the process is ours: it is adopted
# instead of leaving the supervisor stuck.
cat >"$TMP/bin/ps" <<EOF
#!/usr/bin/env bash
printf '%s\n' "python3 $CORE_ROOT/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
rm -f "$SOLAR_HOST_RUNTIME_DIR/host.pid"
start_stub legacy-install "{}"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "identity-less console of this install is adopted" \
  || { fail "identity-less console of this install is adopted (ec=$ec)"; cat "$TMP/live.err" >&2; }
stop_stub
# The same console started from another install stays rejected.
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 /somewhere/else/core/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
start_stub legacy-other-install "{}"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "identity-less console of another install is rejected" \
  || fail "identity-less console of another install is rejected (ec=$ec)"
stop_stub
# Drop the ps double: section 12 must see real command lines again.
rm -f "$TMP/bin/ps"

# --- 12. stop_host.sh never kills what is not a live host_server.py ---------
# No ps double here: the real command lines must classify the pids, or the test
# would only be checking its own fake.
STOP_SCRIPT="$SCRIPTS/stop_host.sh"
sleep 120 & disown 2>/dev/null || true
INNOCENT_PID=$!
printf '%s\n' "$INNOCENT_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
set +e
STOP_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 0 ]] && pass "stop with a reused pid exits 0" \
  || fail "stop with a reused pid exits 0 (ec=$stop_ec: $STOP_OUT)"
grep -q "reused pid" <<<"$STOP_OUT" && pass "stop names the reused pid" \
  || { fail "stop names the reused pid"; echo "$STOP_OUT" >&2; }
kill -0 "$INNOCENT_PID" 2>/dev/null && pass "stop left the reused pid running" \
  || fail "stop left the reused pid running"
[[ ! -f "$SOLAR_HOST_RUNTIME_DIR/host.pid" ]] && pass "stop dropped the stale pid file" \
  || fail "stop dropped the stale pid file"
kill "$INNOCENT_PID" 2>/dev/null || true
wait "$INNOCENT_PID" 2>/dev/null || true
# A pid that is simply gone is stale, not reused: the message must not claim it
# was left running, because there is nothing running to leave.
printf '%s\n' "999999" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
set +e
STOP_OUT="$(bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 0 ]] && pass "stop with a dead pid exits 0" \
  || fail "stop with a dead pid exits 0 (ec=$stop_ec: $STOP_OUT)"
grep -q "stale pid" <<<"$STOP_OUT" && pass "a dead pid is named stale, not reused" \
  || { fail "a dead pid is named stale, not reused"; echo "$STOP_OUT" >&2; }
grep -q "leaving it running" <<<"$STOP_OUT" && fail "a dead pid is said to be left running" \
  || pass "a dead pid is not said to be left running"
[[ ! -f "$SOLAR_HOST_RUNTIME_DIR/host.pid" ]] && pass "the dead pid file was dropped" \
  || fail "the dead pid file was dropped"
# A live host_server.py named by the pid file is this runtime's console and must
# be stopped, not merely dropped: the pid file holds a pid, the helper re-checks
# the identity, and mixing them would silently turn every real stop into a no-op.
sleep 120 & disown 2>/dev/null || true
OWN_STOP_PID=$!
printf '%s\n' "$OWN_STOP_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
cat >"$TMP/bin/ps" <<EOF
#!/usr/bin/env bash
printf '%s\n' "python3 $CORE_ROOT/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
set +e
STOP_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 0 ]] && pass "stop with this runtime's own server exits 0" \
  || fail "stop with this runtime's own server exits 0 (ec=$stop_ec: $STOP_OUT)"
grep -q "OK: Solar Host stopped" <<<"$STOP_OUT" && pass "stop reports the host stopped" \
  || { fail "stop reports the host stopped"; echo "$STOP_OUT" >&2; }
kill -0 "$OWN_STOP_PID" 2>/dev/null && fail "stop left the own server running" \
  || pass "stop really stopped the own server"
rm -f "$TMP/bin/ps"
# A foreign listener is reported and the stop exits 3 (no "not running" lie).
lsof_double
start_stub stop-foreign "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
set +e
STOP_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" FAKE_LSOF_PID="$STUB_PID" bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 3 ]] && pass "stop of a foreign console exits 3" \
  || fail "stop of a foreign console exits 3 (ec=$stop_ec: $STOP_OUT)"
grep -q "not the console of this runtime" <<<"$STOP_OUT" && pass "stop reports why it refuses" \
  || { fail "stop reports why it refuses"; echo "$STOP_OUT" >&2; }
grep -q "not running" <<<"$STOP_OUT" && fail "stop claims a foreign console is not running" \
  || pass "stop does not claim the foreign console is not running"
kill -0 "$STUB_PID" 2>/dev/null && pass "stop left the foreign console running" \
  || fail "stop left the foreign console running"
stop_stub
# An own listener that is ours by identity yet not host_server.py is not stopped
# and the stop must not claim success: exit 4, and no "not running".
start_stub stop-undetainable "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 algo-que-no-es-el-server.py"
EOF
chmod +x "$TMP/bin/ps"
set +e
STOP_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" FAKE_LSOF_PID="$STUB_PID" bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 4 ]] && pass "stop of a non-stoppable own listener exits 4" \
  || fail "stop of a non-stoppable own listener exits 4 (ec=$stop_ec: $STOP_OUT)"
grep -q "not running" <<<"$STOP_OUT" && fail "stop calls a non-stoppable own listener not running" \
  || pass "stop does not call a non-stoppable own listener not running"
kill -0 "$STUB_PID" 2>/dev/null && pass "stop left the non-stoppable own listener running" \
  || fail "stop left the non-stoppable own listener running"
stop_stub
rm -f "$TMP/bin/ps"
# A pid file that names a host_server.py of another workspace is not ours: the
# stop must not kill it just because the command line says host_server.py.
start_stub stop-foreign-pid "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
printf '%s\n' "$STUB_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 host_server.py"
EOF
chmod +x "$TMP/bin/ps"
set +e
STOP_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 3 ]] && pass "stop of a pid file from another workspace exits 3" \
  || fail "stop of a pid file from another workspace exits 3 (ec=$stop_ec: $STOP_OUT)"
kill -0 "$STUB_PID" 2>/dev/null && pass "stop left another workspace's pid file process running" \
  || fail "stop left another workspace's pid file process running"
stop_stub
rm -f "$TMP/bin/ps"
# A reused pid plus an own hung console still holding the port: dropping the pid
# file is not a clean stop, the listener has to be stopped too.
lsof_double
sleep 120 & disown 2>/dev/null || true
REUSED_PID=$!
printf '%s\n' "$REUSED_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
sleep 120 & disown 2>/dev/null || true
OWN_HUNG_PID=$!
# The ps double is pid-aware: the pid file holds a reused pid (a plain sleep),
# while the port's listener is this install's host_server.py.
cat >"$TMP/bin/ps" <<EOF
#!/usr/bin/env bash
_args="\$*"
for _a in \$_args; do
  case "\$_a" in
    $REUSED_PID) printf '%s\n' "sleep 120"; exit 0 ;;
    $OWN_HUNG_PID) printf '%s\n' "python3 $CORE_ROOT/skills/solar-app/scripts/host_server.py"; exit 0 ;;
  esac
done
exit 0
EOF
chmod +x "$TMP/bin/lsof" "$TMP/bin/ps"
set +e
STOP_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" FAKE_LSOF_PID="$OWN_HUNG_PID" bash "$STOP_SCRIPT" 2>&1)"
stop_ec=$?
set -e
[[ "$stop_ec" -eq 0 ]] && pass "stop with a reused pid still stops an own hung console" \
  || fail "stop with a reused pid still stops an own hung console (ec=$stop_ec: $STOP_OUT)"
kill -0 "$OWN_HUNG_PID" 2>/dev/null && fail "own hung console survived the reused-pid stop" \
  || pass "own hung console was stopped after the reused pid"
kill -0 "$REUSED_PID" 2>/dev/null && pass "reused pid itself was left running" \
  || fail "reused pid itself was left running"
kill "$REUSED_PID" 2>/dev/null || true
wait "$REUSED_PID" 2>/dev/null || true
kill "$OWN_HUNG_PID" 2>/dev/null || true
wait "$OWN_HUNG_PID" 2>/dev/null || true
rm -f "$TMP/bin/ps"

# --- 13. The console port override is test-only ----------------------------
# A real installation keeps 9000 even when the override leaks into the
# environment; only a temporary runtime honors it.
LIVE_PORT="$(env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA SOLAR_APP_PORT_OVERRIDE=1234 \
  bash -c 'source "$1"; solar_host_load_env; printf "%s" "$SOLAR_APP_PORT"' _ "$HOST_LIB")"
[[ "$LIVE_PORT" == "9000" ]] && pass "a real runtime ignores the port override" \
  || fail "a real runtime ignores the port override (got $LIVE_PORT)"
TEMP_PORT="$(SOLAR_APP_PORT_OVERRIDE=1234 \
  bash -c 'source "$1"; solar_host_load_env; printf "%s" "$SOLAR_APP_PORT"' _ "$HOST_LIB")"
[[ "$TEMP_PORT" == "1234" ]] && pass "a temporary runtime honors the port override" \
  || fail "a temporary runtime honors the port override (got $TEMP_PORT)"

# The suite must not have touched the machine's real console: port 9000 has the
# same listeners before the suite runs and now (it is recorded at the top of this
# file, before any stub), and the override is what keeps the stubs away from it.
REAL_9000_AFTER="$(/usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
[[ "$REAL_9000_AFTER" == "$REAL_9000_BEFORE" ]] && pass "the real console on 9000 is untouched" \
  || fail "the real console on 9000 changed (before='$REAL_9000_BEFORE' after='$REAL_9000_AFTER')"

# --- 14. start_host.sh recovers an own hung console instead of failing ------
# An own console that answers nothing and holds the port must be stopped so the
# new process can bind; the run must not end with "port busy" on its own install.
sleep 120 & disown 2>/dev/null || true
START_HUNG_PID=$!
printf '%s\n' "$START_HUNG_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
lsof_double
cat >"$TMP/bin/ps" <<EOF
#!/usr/bin/env bash
printf '%s\n' "python3 $CORE_ROOT/skills/solar-app/scripts/host_server.py"
EOF
chmod +x "$TMP/bin/ps"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" FAKE_LSOF_PID="$START_HUNG_PID" \
  bash -c 'source "$1"; solar_host_stop_orphan_listeners; echo "ec=$?"' _ "$HOST_LIB" >"$TMP/start-hung.out" 2>&1
kill -0 "$START_HUNG_PID" 2>/dev/null
hung_alive=$?
set -e
[[ "$hung_alive" -ne 0 ]] && pass "start recovery stopped the own hung console" \
  || fail "start recovery stopped the own hung console (pid $START_HUNG_PID alive)"
grep -q "ec=0" "$TMP/start-hung.out" && pass "own hung console stop reports success" \
  || { fail "own hung console stop reports success"; cat "$TMP/start-hung.out" >&2; }
kill "$START_HUNG_PID" 2>/dev/null || true
wait "$START_HUNG_PID" 2>/dev/null || true
rm -f "$TMP/bin/ps"

# --- 15. start_host.sh never kills a host_server.py of another workspace ------
# The pid file names a live host_server.py, but its /health answers as another
# workspace: reading "host_server.py" is not enough to kill it.
START_SCRIPT="$SCRIPTS/start_host.sh"
start_stub start-foreign-pid "{\"workspace\":\"$TMP/another-workspace\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
printf '%s\n' "$STUB_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
cat >"$TMP/bin/ps" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "python3 host_server.py"
EOF
chmod +x "$TMP/bin/ps"
set +e
START_OUT="$(PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" bash "$START_SCRIPT" 2>&1)"
start_ec=$?
set -e
[[ "$start_ec" -eq 3 ]] && pass "start of a foreign console exits 3" \
  || fail "start of a foreign console exits 3 (ec=$start_ec: $START_OUT)"
grep -q "not this runtime's console" <<<"$START_OUT" \
  && pass "start names the foreign pid file process" \
  || { fail "start names the foreign pid file process"; echo "$START_OUT" >&2; }
kill -0 "$STUB_PID" 2>/dev/null && pass "start left the foreign console running" \
  || fail "start left the foreign console running"
stop_stub
rm -f "$TMP/bin/ps"

# --- 16. The supervisor's healthy path runs no lsof --------------------------
# With a complete identity in /health, check_host.sh must resolve no listener:
# an lsof double that fails the run when used proves the call is lazy.
start_stub lazy-identity "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
cat >"$TMP/bin/lsof" <<'EOF'
#!/usr/bin/env bash
echo "lsof was called on the healthy path" >&2
exit 1
EOF
chmod +x "$TMP/bin/lsof"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "a healthy console passes --liveness without lsof" \
  || { fail "a healthy console passes --liveness without lsof (ec=$ec)"; cat "$TMP/live.err" >&2; }
grep -q "lsof was called" "$TMP/live.err" && fail "lsof ran on the healthy path" \
  || pass "lsof did not run on the healthy path"
stop_stub
rm -f "$TMP/bin/lsof"

# --- 17. start_host.sh repairs a stale pid file when the console answers ------
# The pid file names a dead pid while our own console answers /health: the run
# must report the real listener, not the dead pid, and repair the pid file.
start_stub stale-pidfile "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
printf '%s\n' "999999" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
set +e
START_OUT="$(bash "$START_SCRIPT" 2>&1)"
start_ec=$?
set -e
[[ "$start_ec" -eq 0 ]] && pass "start with a stale pid file exits 0 when the console answers" \
  || fail "start with a stale pid file exits 0 when the console answers (ec=$start_ec: $START_OUT)"
grep -q "already running (pid $STUB_PID)" <<<"$START_OUT" \
  && pass "start reports the listener that really answers" \
  || { fail "start reports the listener that really answers"; echo "$START_OUT" >&2; }
[[ "$(cat "$SOLAR_HOST_RUNTIME_DIR/host.pid" 2>/dev/null)" == "$STUB_PID" ]] \
  && pass "start repaired the stale pid file" \
  || fail "start repaired the stale pid file (got $(cat "$SOLAR_HOST_RUNTIME_DIR/host.pid" 2>/dev/null))"
stop_stub

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
