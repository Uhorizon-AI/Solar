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
sleep 120 &
OWN_SERVER_PID=$!
printf '%s\n' "$OWN_SERVER_PID" >"$SOLAR_HOST_RUNTIME_DIR/host.pid"
start_stub legacy-own "{}"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -eq 0 ]] && pass "identity-less console with this runtime's pid file is adopted" \
  || { fail "identity-less console with this runtime's pid file is adopted (ec=$ec)"; cat "$TMP/live.err" >&2; }
stop_stub
kill "$OWN_SERVER_PID" 2>/dev/null || true
wait "$OWN_SERVER_PID" 2>/dev/null || true

# --- 6. Legacy health with no identity and no pid file ----------------------
rm -f "$SOLAR_HOST_RUNTIME_DIR/host.pid"
start_stub legacy-orphan "{}"
set +e
PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin" liveness
ec=$?
set -e
[[ "$ec" -ne 0 ]] && pass "identity-less console without a pid file is rejected" \
  || fail "identity-less console without a pid file is rejected (ec=$ec)"
grep -q "without identity and without this runtime" "$TMP/live.err" \
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

# --- 8. solar_host_stop_orphan_listeners never kills a foreign console ------
# A lsof double names the listener; a ps double makes it look like
# host_server.py; the stub on the chosen port decides the identity.
cat >"$TMP/bin/lsof" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${FAKE_LSOF_PID:-999999}"
EOF
chmod +x "$TMP/bin/lsof"
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

# --- 9. No residue: the stub port has no listener after the stub stops ------
start_stub residue "{\"workspace\":\"$SOLAR_WORKSPACE\",\"runtime\":\"$SOLAR_RUNTIME_ROOT\"}"
before="$(/usr/sbin/lsof -nP -iTCP:"$STUB_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
[[ -n "$before" ]] && pass "stub held the port while running" || fail "stub held the port while running"
stop_stub
after="$(/usr/sbin/lsof -nP -iTCP:"$STUB_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
[[ -z "$after" ]] && pass "no new listener left on the stub port" \
  || fail "no new listener left on the stub port (pids=$after)"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
