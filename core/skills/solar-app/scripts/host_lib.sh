#!/usr/bin/env bash
# host_lib.sh — Solar Host paths, console identity and API base URL.
set -euo pipefail

_HOST_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PATHS_SCRIPTS="$(cd "$_HOST_LIB_DIR/../../solar-paths/scripts" && pwd)"
# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$_PATHS_SCRIPTS/resolve_solar_paths.sh"
# shellcheck source=../../solar-paths/scripts/solar_runtime_paths.sh
source "$_PATHS_SCRIPTS/solar_runtime_paths.sh"
# shellcheck source=host_env_compat.sh
source "$_HOST_LIB_DIR/host_env_compat.sh"

solar_host_workspace_gateway_port() {
  local ws="$1"
  python3 "$_HOST_LIB_DIR/host_registry.py" gateway-port "$ws"
}

solar_host_apply_active_registry() {
  local active=""
  active="$(python3 "$_HOST_LIB_DIR/host_registry.py" active 2>/dev/null || true)"
  if [[ -n "$active" && -d "$active" ]]; then
    export SOLAR_WORKSPACE="$active"
  fi
}

solar_host_load_env() {
  solar_resolve_paths --quiet
  solar_host_apply_active_registry
  if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SOLAR_WORKSPACE/.env"
    set +a
  fi
  solar_app_apply_legacy_env
  if [[ -z "${SOLAR_HTTP_PORT:-}" ]]; then
    _gw="$(solar_host_workspace_gateway_port "$SOLAR_WORKSPACE")"
    export SOLAR_HTTP_PORT="${_gw:-8787}"
  fi
  export SOLAR_APP_HOST="${SOLAR_APP_HOST:-127.0.0.1}"
  # The console port is fixed at 9000. SOLAR_APP_PORT_OVERRIDE exists only for
  # tests, so a stub can stay off the machine's real console port: it is honored
  # only when the runtime is a temporary one, never in a real installation.
  if [[ -n "${SOLAR_APP_PORT_OVERRIDE:-}" ]] && solar_host_runtime_is_temporary; then
    export SOLAR_APP_PORT="$SOLAR_APP_PORT_OVERRIDE"
  else
    export SOLAR_APP_PORT=9000
  fi
  export SOLAR_APP_BASE_URL="http://${SOLAR_APP_HOST}:${SOLAR_APP_PORT}"
  # Host state is machine state: it lives under the framework runtime root,
  # never inside the workspace. A relative override stays relative to the
  # workspace for backward compatibility with explicit deployments.
  if [[ -z "${SOLAR_HOST_RUNTIME_DIR:-}" ]]; then
    export SOLAR_HOST_RUNTIME_DIR="$(solar_runtime_dir host)"
  fi
  export SOLAR_HOST_PID_FILE="$(solar_host_runtime_path)/host.pid"
}

# Absolute host runtime dir (does not create it).
solar_host_runtime_path() {
  case "$SOLAR_HOST_RUNTIME_DIR" in
    /*) printf '%s\n' "$SOLAR_HOST_RUNTIME_DIR" ;;
    *)  printf '%s\n' "$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR" ;;
  esac
}

solar_host_runtime_dir() {
  solar_host_load_env
  local dir
  dir="$(solar_host_runtime_path)"
  mkdir -p "$dir"
  printf '%s\n' "$dir"
}

# True when the runtime this shell would use is a temporary one, never the
# machine's own. Mirrors the guard's rule (solar_test_guard): the resolved
# runtime must differ from the machine runtime (solar-paths with the test
# overrides removed), compared on physical paths.
#
# The answer is cached in this shell, not across processes: each call shells out
# twice and helpers call it repeatedly, so a second call in the same shell is
# free. The cache is keyed on the runtime inputs it depends on, so a caller that
# changes SOLAR_RUNTIME_ROOT (or SOLAR_APP_DATA) mid-shell gets a fresh answer
# instead of the stale one.
_solar_host_temp_runtime=""
_solar_host_temp_runtime_key=""
solar_host_runtime_is_temporary() {
  local key="${SOLAR_RUNTIME_ROOT:-}|${SOLAR_APP_DATA:-}"
  if [[ -n "${_solar_host_temp_runtime:-}" && "$key" == "$_solar_host_temp_runtime_key" ]]; then
    [[ "$_solar_host_temp_runtime" == yes ]]
    return
  fi
  local live resolved py
  py="$(cd "$_PATHS_SCRIPTS" && pwd)/solar_runtime.py"
  if [[ ! -f "$py" ]]; then
    _solar_host_temp_runtime="no"
    _solar_host_temp_runtime_key="$key"
    return 1
  fi
  if ! live="$(env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA python3 "$py" runtime 2>/dev/null)"; then
    _solar_host_temp_runtime="no"
    _solar_host_temp_runtime_key="$key"
    return 1
  fi
  if ! resolved="$(python3 "$py" runtime 2>/dev/null)"; then
    _solar_host_temp_runtime="no"
    _solar_host_temp_runtime_key="$key"
    return 1
  fi
  live="$(solar_canonical_path "$live")"
  resolved="$(solar_canonical_path "$resolved")"
  _solar_host_temp_runtime_key="$key"
  if [[ "$resolved" != "$live" ]]; then
    _solar_host_temp_runtime="yes"
    return 0
  fi
  _solar_host_temp_runtime="no"
  return 1
}

# Effective identity of the console this machine should serve: physical paths.
# /health reports the same pair, so a console of another workspace or another
# runtime is never mistaken for ours.
solar_host_identity_workspace() {
  solar_host_load_env
  solar_canonical_path "$SOLAR_WORKSPACE"
}

solar_host_identity_runtime() {
  solar_runtime_root
}

# The install this runtime was started from, as a physical path. There is one
# layout: the install root holds core/, and solar-app sits at
# <install>/core/skills/solar-app, so the root is four levels up from these
# scripts. Everything is derived from the script location, never the environment.
solar_host_identity_install_roots() {
  local root
  # A layout without that level (an isolated checkout) must not abort the
  # process substitution under `set -e`; the path is printed only when it exists.
  if root="$(cd "$_HOST_LIB_DIR/../../../.." 2>/dev/null && pwd -P)"; then
    [[ -d "$root" ]] && printf '%s\n' "$root"
  fi
}

# The single identity policy lives in host_identity.py. Everything here calls
# it, so no reuse path can drift: /health must report this runtime's workspace
# and runtime, and a console that reports no identity — or only half of it — is
# adopted only with a proof that the process is ours (this runtime's pid file or
# this install's host_server.py in the listener command).
solar_host_identity_own() {
  local health_file="$1"
  local pid_file="${2-}"
  local listener_pids="${3-}"
  local -a roots=()
  while IFS= read -r root; do
    [[ -n "$root" ]] && roots+=(--install-root "$root")
  done < <(solar_host_identity_install_roots)
  python3 "$_HOST_LIB_DIR/host_identity.py" evaluate \
    --health-file "$health_file" \
    --workspace "$(solar_host_identity_workspace)" \
    --runtime "$(solar_host_identity_runtime)" \
    --pid-file "$pid_file" \
    --listener-pids "$listener_pids" \
    "${roots[@]+"${roots[@]}"}"
}

# True when a command line runs this install's host_server.py.
solar_host_command_is_install_server() {
  local command="${1-}"
  [[ -n "$command" ]] || return 1
  local -a roots=()
  while IFS= read -r root; do
    [[ -n "$root" ]] && roots+=(--install-root "$root")
  done < <(solar_host_identity_install_roots)
  python3 "$_HOST_LIB_DIR/host_identity.py" command-is-install-server \
    --command "$command" "${roots[@]+"${roots[@]}"}"
}

# Tested identity of the console on SOLAR_APP_BASE_URL. Echoes one of:
#   own        the console is this runtime's own
#   foreign    the console answered and is another workspace's or runtime's
#   unproven   nothing answered, or it answered without identity and without a
#              proof that the process is ours
# Callers must not flatten "unproven" into "foreign": an own console that is
# merely hung (no /health, no pid file, but this install's host_server.py in its
# command line) has to stay recoverable.
# The endpoint verdict of one pid against the probed socket, from a
# `solar_host_port_endpoints` blob: "match", "other", or "unknown" when the blob
# does not list that pid (no endpoint evidence, so the caller keeps its proofs).
solar_host_endpoint_state_for() {
  local pid="${1-}" blob="${2-}" listed state
  [[ -n "$pid" ]] || { printf '%s\n' unknown; return 0; }
  while read -r listed state; do
    if [[ "$listed" == "$pid" ]]; then
      printf '%s\n' "$state"
      return 0
    fi
  done <<<"$blob"
  printf '%s\n' unknown
}

# Tested identity of the console on SOLAR_APP_BASE_URL. Echoes one of:
#   own        the console is this runtime's own
#   foreign    the console answered and is another workspace's or runtime's
#   unproven   nothing answered, or it answered without identity and without a
#              proof that the process is ours
# Callers must not flatten "unproven" into "foreign": an own console that is
# merely hung (no /health, no pid file, but this install's host_server.py in its
# command line) has to stay recoverable.
#
# ``$2`` is the pid's endpoint verdict ("match"/"other"/"unknown") the caller
# already resolved from one ``solar_host_port_endpoints`` call, so a loop over
# the port pays for one lsof, not one per pid. Omitted, it is resolved here.
solar_host_listener_identity() {
  solar_host_load_env
  local pid="${1-}" endpoint_state="${2-}" health_file listener_command status
  [[ -n "$pid" ]] || pid="$(solar_host_port_listener_pids | head -n1 || true)"
  [[ -n "$endpoint_state" ]] || endpoint_state="$(solar_host_endpoint_state_for "$pid" "$(solar_host_port_endpoints)")"
  listener_command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  # Endpoint evidence: when lsof proves this pid listens only on an address other
  # than the probed one, the /health answer — which the probe fetched from
  # SOLAR_APP_BASE_URL — is not this pid's, so it must not be attributed to it.
  # A foreign console on another address would otherwise borrow the answer of our
  # own console on the probed address and be labelled own and stopped. This is
  # also a hard exclusion for the command/pid-file proofs below: those prove the
  # *process* is this install's server, never that it serves the probed socket,
  # so a process on another address (or another family) must not become "own"
  # through them either. The caller (the orphan sweep) also skips "other" before
  # calling this, but the exclusion holds inside this function too, so no direct
  # caller can stop a listener that does not hold the probed socket. "unknown"
  # (no lsof, or nothing listed) is not "other": the failsafe below still
  # recovers a hung own console.
  if [[ "$endpoint_state" == other ]]; then
    echo unproven
    return 0
  fi
  health_file="$(mktemp "${TMPDIR:-/tmp}/solar-host-health.XXXXXX")"
  if ! python3 - "$SOLAR_APP_BASE_URL" "$health_file" <<'PY'
import json, sys, urllib.request
base, dest = sys.argv[1:3]
# A loopback probe must never go through an environment proxy: with http_proxy
# set, urlopen would route it through the proxy and could fail (or reach
# something that is not the console), turning a healthy console into unproven.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(base + "/health", timeout=3) as response:
        data = json.load(response)
except Exception:
    raise SystemExit(1)
with open(dest, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
  then
    # No usable answer for THIS listener (no answer, or the answer came from
    # another socket). It is ours only via a proof of the process itself: this
    # install's host_server.py in its command line, or this runtime's pid file
    # naming that very listener.
    if solar_host_command_is_install_server "$listener_command"; then
      echo own
    elif [[ -n "$pid" ]] && solar_host_pid_file_names "$SOLAR_HOST_PID_FILE" "$pid"; then
      echo own
    else
      echo unproven
    fi
    rm -f "$health_file"
    return 0
  fi
  set +e
  # Only the pid under test is handed to the policy: the caller asked about this
  # one listener, and passing the whole port list would let a different listener
  # satisfy the pid-file proof for it. The reason is captured to tell a proven
  # foreign console ("another workspace/runtime") from an unproven one.
  local reason
  reason="$(solar_host_identity_own "$health_file" "$SOLAR_HOST_PID_FILE" "$pid" 2>&1)"
  status=$?
  set -e
  rm -f "$health_file"
  if [[ "$status" -eq 0 ]]; then
    echo own
  elif [[ "$reason" == *"another workspace"* || "$reason" == *"another runtime"* ]]; then
    echo foreign
  else
    # It answered but its identity is incomplete and no proof was found: that is
    # "unproven", not "foreign". The message must not assert more than we know.
    echo unproven
  fi
}

# PIDs listening on SOLAR_APP_HOST:SOLAR_APP_PORT (orphan recovery when host.pid is missing).
solar_host_port_listener_pids() {
  solar_host_load_env
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  lsof -nP -iTCP:"$SOLAR_APP_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -n -u || true
}

# The socket the probe really reaches, as "host:port": the listener on any other
# address of the same port is a different socket and must not be attributed the
# /health answer a probe of this address returns.
solar_host_probe_endpoint() {
  solar_host_load_env
  printf '%s:%s\n' "$SOLAR_APP_HOST" "$SOLAR_APP_PORT"
}

# PIDs that hold the very socket the console binds: SOLAR_APP_HOST:SOLAR_APP_PORT.
# A listener of the same port on another address does not block that bind and is
# not the console the supervisor talks to, so it is left out of the port sweep:
# only the listeners of the probed endpoint can free the port the run needs.
#
# With no endpoint evidence at all (lsof missing, or a double that only answers
# `-t`) every listener is returned, which is the pre-endpoint behaviour: the
# fallback must never hide a listener the sweep has to report.
solar_host_port_listener_pids_on_endpoint() {
  solar_host_load_env
  local listed pid state
  listed="$(solar_host_port_endpoints)"
  if [[ -z "$listed" ]]; then
    solar_host_port_listener_pids
    return 0
  fi
  while read -r pid state; do
    [[ -n "$pid" ]] || continue
    [[ "$state" == match ]] && printf '%s\n' "$pid"
  done <<<"$listed"
}

# Print "pid match|other" for every listener of the port, one lsof call for the
# whole port. Empty when lsof is missing or listed nothing: the caller then has no
# endpoint evidence and falls back to its other proofs.
solar_host_port_endpoints() {
  solar_host_load_env
  command -v lsof >/dev/null 2>&1 || return 0
  python3 "$_HOST_LIB_DIR/host_identity.py" port-endpoints \
    --host "$SOLAR_APP_HOST" --port "$SOLAR_APP_PORT" 2>/dev/null || true
}

solar_host_pid_looks_like_server() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  # Substring prefilter only: it says the process runs *some* host_server.py,
  # never that the server is this install's own (that is
  # command_is_install_server, in host_identity.py). It is never enough on its
  # own to kill or adopt a process — every caller combines it with an identity
  # check — and it mirrors ``pid_is_host_server`` so the two cannot drift.
  solar_host_command_looks_like_server "$(ps -p "$pid" -o args= 2>/dev/null || true)"
}

# True when a command line names host_server.py at all. This is the same lax
# prefilter as host_identity.pid_is_host_server; it is NOT a proof of ownership
# and the install check is command_is_install_server in host_identity.py.
solar_host_command_looks_like_server() {
  [[ "$1" == *host_server.py* ]]
}

# True when the pid file at $1 names the pid $2 (the live listener) and that pid
# runs this install's own host_server.py. The rule lives in host_identity.py
# (single policy); this is only the shell wrapper around it.
solar_host_pid_file_names() {
  local pid_file="${1-}" wanted="${2-}"
  [[ -n "$pid_file" && -n "$wanted" && -f "$pid_file" ]] || return 1
  local -a roots=()
  while IFS= read -r root; do
    [[ -n "$root" ]] && roots+=(--install-root "$root")
  done < <(solar_host_identity_install_roots)
  python3 "$_HOST_LIB_DIR/host_identity.py" pid-file-names-listener \
    --pid-file "$pid_file" --pid "$wanted" "${roots[@]+"${roots[@]}"}"
}

# Human-readable owner of the port. Never stops anything. ``$2`` is the tested
# identity ("foreign" or "unproven"): a console that answered as another
# workspace is foreign; one that did not answer and had no proof is only
# unproven, and the message must not claim to know more than that.
solar_host_report_foreign_listener() {
  solar_host_load_env
  local pid="${1-}" identity="${2:-foreign}" args
  [[ -n "$pid" ]] || pid="$(solar_host_port_listener_pids | head -n1 || true)"
  [[ -n "$pid" ]] || return 0
  args="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  {
    if [[ "$identity" == unproven ]]; then
      echo "ERROR: :$SOLAR_APP_PORT is held by pid $pid, whose identity could not be proven to be this runtime's console."
    else
      echo "ERROR: :$SOLAR_APP_PORT is held by pid $pid, which is not the console of this runtime."
    fi
    [[ -n "$args" ]] && echo "  command: $args"
    echo "  expected workspace: $(solar_host_identity_workspace)"
    echo "  expected runtime:   $(solar_host_identity_runtime)"
    echo "Solar will not stop it. Check its identity first, then retire it by hand:"
    echo "  ps -p $pid -o command= && curl -s http://${SOLAR_APP_HOST}:${SOLAR_APP_PORT}/health"
    echo "  kill $pid   # only after the identity above matches nothing you need"
  } >&2
}

solar_host_stop_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  local _i
  for _i in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.2
  done
  kill -9 "$pid" 2>/dev/null || true
}

# Stop listeners of the port only when they are this runtime's own console.
# "Own" means the /health payload names this workspace and runtime, or — for a
# console that reports no identity — a proof that the process is ours (this
# install's host_server.py in its command line). Anything else, including a
# listener that cannot be proven either way, is reported and left running.
#
# Return contract: 0 when at least one own listener was stopped, 1 when the port
# had none (or none was own), 2 when a listener was foreign, 4 when the port is
# held by a listener that is ours by identity but cannot be stopped (its command
# line is not host_server.py). A foreign listener anywhere in the list wins over
# having stopped another one, because the caller must not report a clean stop
# while a foreign console still holds the port; a non-stoppable own listener wins
# over 0/1 for the same reason.
solar_host_stop_orphan_listeners() {
  solar_host_load_env
  local stopped=0 foreign=0 unstoppable=0
  local pid identity endpoints endpoint_state
  # One lsof for the whole port, then one classification per listener.
  endpoints="$(solar_host_port_endpoints)"
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    endpoint_state="$(solar_host_endpoint_state_for "$pid" "$endpoints")"
    # A listener of the same port on another address does not hold the socket the
    # console binds (SOLAR_APP_HOST:SOLAR_APP_PORT) and is not the console the
    # supervisor talks to: leave it alone and do not call it foreign, or a
    # legitimate console on another loopback address would block every run.
    [[ "$endpoint_state" == other ]] && continue
    identity="$(solar_host_listener_identity "$pid" "$endpoint_state")"
    if [[ "$identity" == own ]] && solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: stopping orphan Solar Host listener (pid $pid on :$SOLAR_APP_PORT)" >&2
      solar_host_stop_pid "$pid"
      stopped=1
      continue
    fi
    if [[ "$identity" == own ]]; then
      # Ours by identity, but its command line is not host_server.py: do not kill
      # it and do not label it foreign. Report the concrete reason and flag it so
      # the caller does not report "not running" while the port is still held.
      echo "WARN: listener pid $pid on :$SOLAR_APP_PORT is ours by identity but is not host_server.py — leaving it running" >&2
      unstoppable=1
      continue
    fi
    solar_host_report_foreign_listener "$pid" "$identity"
    foreign=1
  done < <(solar_host_port_listener_pids)
  [[ "$foreign" -eq 1 ]] && return 2
  [[ "$unstoppable" -eq 1 ]] && return 4
  [[ "$stopped" -eq 1 ]]
}

# Interpret the code solar_host_stop_orphan_listeners returned when the port is
# still held: print the concrete reason and return the exit code the caller must
# use (3 foreign, 4 own-but-not-stoppable), or 1 when there is nothing to refuse.
# The message lives here so start_host.sh and stop_host.sh cannot drift apart.
# The foreign listener itself was already reported by the stopper.
solar_host_report_port_blocker() {
  solar_host_load_env
  case "${1:-}" in
    2)
      echo "ERROR: the console port :${SOLAR_APP_PORT} is held by a foreign console; it was not stopped." >&2
      return 3
      ;;
    4)
      echo "ERROR: the console port :${SOLAR_APP_PORT} is held by an own listener that is not host_server.py; it was not stopped." >&2
      return 4
      ;;
    *) return 1 ;;
  esac
}

# Guard for the reuse path: when something holds the console port and no
# listener is this runtime's own console, report it and return 3. Retrying cannot
# converge, so every caller (start_host.sh, ensure_host.sh) stops here with the
# same message. An own hung console (this install's host_server.py in its command
# line) is not this case: it returns 0 and the caller may recover it. Returns 0 —
# and does nothing — when the port is free or any listener is provably ours.
solar_host_refuse_foreign_listener() {
  solar_host_load_env
  local pid identity endpoints endpoint_state first_blocker_pid="" first_blocker_identity=""
  # Every listener is examined: with two listeners, a foreign first pid must not
  # stop the run while the second is this runtime's own console. A listener on
  # another address of the same port is not in the way, so it is skipped.
  endpoints="$(solar_host_port_endpoints)"
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    endpoint_state="$(solar_host_endpoint_state_for "$pid" "$endpoints")"
    [[ "$endpoint_state" == other ]] && continue
    identity="$(solar_host_listener_identity "$pid" "$endpoint_state")"
    if [[ "$identity" == own ]]; then
      return 0
    fi
    if [[ -z "$first_blocker_pid" ]]; then
      first_blocker_pid="$pid"
      first_blocker_identity="$identity"
    fi
  done < <(solar_host_port_listener_pids)
  [[ -n "$first_blocker_pid" ]] || return 0
  # Pass the tested identity through: "foreign" (it answered as another
  # workspace or runtime) and "unproven" (it did not answer and no proof was
  # found) are different claims, and the message must say which one it is.
  solar_host_report_foreign_listener "$first_blocker_pid" "$first_blocker_identity"
  return 3
}
