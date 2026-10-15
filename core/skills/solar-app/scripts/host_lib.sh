#!/usr/bin/env bash
# host_lib.sh — Solar Host paths and API base URL.
set -euo pipefail

_HOST_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PATHS_SCRIPTS="$(cd "$_HOST_LIB_DIR/../../solar-paths/scripts" && pwd)"
# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$_PATHS_SCRIPTS/resolve_solar_paths.sh"
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
  # The test-only port override comes from the process environment, never from a
  # workspace .env: keep what the caller set and drop what .env adds.
  local _tm_set="${SOLAR_APP_TEST_MODE+x}" _tm="${SOLAR_APP_TEST_MODE-}"
  local _tp_set="${SOLAR_APP_TEST_PORT+x}" _tp="${SOLAR_APP_TEST_PORT-}"
  if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SOLAR_WORKSPACE/.env"
    set +a
  fi
  unset SOLAR_APP_TEST_MODE SOLAR_APP_TEST_PORT
  [[ -z "$_tm_set" ]] || export SOLAR_APP_TEST_MODE="$_tm"
  [[ -z "$_tp_set" ]] || export SOLAR_APP_TEST_PORT="$_tp"
  solar_app_apply_legacy_env
  if [[ -z "${SOLAR_HTTP_PORT:-}" ]]; then
    _gw="$(solar_host_workspace_gateway_port "$SOLAR_WORKSPACE")"
    export SOLAR_HTTP_PORT="${_gw:-8787}"
  fi
  export SOLAR_APP_HOST="${SOLAR_APP_HOST:-127.0.0.1}"
  # The console port is 9000. A test can move it only with SOLAR_APP_TEST_MODE=1 and SOLAR_APP_TEST_PORT both in the process environment (never from a .env, never to 9000).
  # Resolver failure falls back to 9000.
  SOLAR_APP_PORT="$(python3 "$_HOST_LIB_DIR/host_identity.py" port 2>/dev/null || echo 9000)"
  export SOLAR_APP_PORT
  export SOLAR_APP_BASE_URL="http://${SOLAR_APP_HOST}:${SOLAR_APP_PORT}"
  # Host state is machine state: it lives under the framework runtime root,
  # never inside the workspace. A relative override stays relative to the
  # workspace for backward compatibility with explicit deployments.
  if [[ -z "${SOLAR_HOST_RUNTIME_DIR:-}" ]]; then
    # shellcheck source=/dev/null
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../solar-paths/scripts" && pwd)/solar_runtime_paths.sh"
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

# --- Console identity and process ownership -------------------------------------
# One policy (host_identity.py) decides whether the console on the port is this
# one. These helpers add the process-level proof of ownership. No function here
# signals a process unless its command line is host_server.py (re-checked right
# before each signal) and ownership was shown by identity, by this runtime's pid
# file, or by this install's script path.

# PIDs listening on exactly SOLAR_APP_HOST:SOLAR_APP_PORT (the address the probe uses). Empty without lsof: no
# caller may then adopt or stop an unidentified console. Listeners on another
# address (another loopback address, LAN or wildcard) is not this console and is never returned.
solar_host_port_listener_pids() {
  solar_host_load_env
  python3 "$_HOST_LIB_DIR/host_identity.py" listeners "$SOLAR_APP_PORT" "$SOLAR_APP_HOST"
}

# Sets HOST_STATE, HOST_REASON, HOST_OBSERVED_WORKSPACE, HOST_OBSERVED_RUNTIME and
# HOST_OBSERVED_PID (the pid the console itself reports; empty for older consoles).
# Requires solar_host_load_env. Never exits non-zero.
#
# One extra state: stale_workspace. The runtime matches and only the workspace differs
# (the active workspace was switched with `solar app workspace use` while the console
# ran) AND this runtime's pid file points at the very pid that answered. That console
# is ours: it is not reusable (check_host still exits 3) but it is stopped and replaced.
solar_host_assess() {
  local line differing="" recorded=""
  line="$(python3 "$_HOST_LIB_DIR/host_identity.py" assess --base-url "$SOLAR_APP_BASE_URL" \
    --workspace "$SOLAR_WORKSPACE" 2>/dev/null || true)"
  IFS=$'\t' read -r HOST_STATE HOST_REASON HOST_OBSERVED_WORKSPACE HOST_OBSERVED_RUNTIME \
    HOST_OBSERVED_PID differing <<<"$line" || true
  HOST_STATE="${HOST_STATE:-unreachable}"
  HOST_REASON="${HOST_REASON:-console unreachable}"
  HOST_OBSERVED_PID="${HOST_OBSERVED_PID:-}"
  if [[ "$HOST_STATE" == "mismatch" && "$differing" == "workspace" && -n "$HOST_OBSERVED_PID" \
        && -f "$SOLAR_HOST_PID_FILE" ]]; then
    recorded="$(tr -d '[:space:]' <"$SOLAR_HOST_PID_FILE" 2>/dev/null || true)"
    if [[ "$recorded" == "$HOST_OBSERVED_PID" ]] && solar_host_pid_looks_like_server "$recorded"; then
      HOST_STATE="stale_workspace"
      HOST_REASON="this runtime's console still serves the previous workspace"
    fi
  fi
}

solar_host_pid_looks_like_server() {
  local pid="$1" args
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  args="$(ps -ww -p "$pid" -o args= 2>/dev/null)" || return 1
  [[ "$args" =~ (^|[[:space:]/])host_server\.py($|[[:space:]]) ]]
}

# True when the process runs THIS install's host_server.py. Compared as the path
# the library was loaded from and as its physical path (symlinked installs).
solar_host_pid_is_this_install() {
  local pid="$1" args script
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  args="$(ps -ww -p "$pid" -o args= 2>/dev/null)" || return 1
  for script in "$_HOST_LIB_DIR/host_server.py" "$(cd -P "$_HOST_LIB_DIR" && pwd -P)/host_server.py"; do
    # Anchored: the whole path must start the command line or follow a space.
    [[ "$args" == "$script" || "$args" == "$script "* || "$args" == *" $script" || "$args" == *" $script "* ]] \
      && return 0
  done
  return 1
}

# True when the pid a console reported is really the listener of SOLAR_APP_HOST:port.
# Without lsof nothing can be cross-checked and the report is accepted.
solar_host_reported_pid_is_listener() {
  local pid="$1"
  command -v lsof >/dev/null 2>&1 || return 0
  grep -qx "$pid" <<<"$(solar_host_port_listener_pids)"
}

# The pid recorded for this runtime, if it is alive and still a host_server.py
# (a recycled pid is rejected). While a console answers and listeners are known,
# the pid must also be one of them. Args: assessed state.
solar_host_pidfile_pid() {
  local state="${1:-unreachable}" pid listeners
  [[ -f "$SOLAR_HOST_PID_FILE" ]] || return 1
  pid="$(tr -d '[:space:]' <"$SOLAR_HOST_PID_FILE" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  solar_host_pid_looks_like_server "$pid" || return 1
  case "$state" in
    match|stale_workspace)
      # The console names its own pid: the recorded one must be that process.
      [[ -z "${HOST_OBSERVED_PID:-}" || "$pid" == "$HOST_OBSERVED_PID" ]] || return 1
      [[ -z "${HOST_OBSERVED_PID:-}" ]] || solar_host_reported_pid_is_listener "$pid" || return 1
      ;;
    legacy|partial)
      listeners="$(solar_host_port_listener_pids)"
      if [[ -n "$listeners" ]] && ! grep -qx "$pid" <<<"$listeners"; then
        return 1
      fi
      ;;
  esac
  printf '%s\n' "$pid"
}

# Stops one process, only if it is still a host_server.py. Returns 1 if refused.
solar_host_stop_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if ! solar_host_pid_looks_like_server "$pid"; then
    echo "WARN: pid $pid is not a Solar console (host_server.py); not signalled" >&2
    return 1
  fi
  kill "$pid" 2>/dev/null || true
  local _i
  for _i in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.2
  done
  if solar_host_pid_looks_like_server "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi
}

# Diagnostic for a console that is not this one. States what it serves, that
# nothing was stopped, who removes it and how. Never retried automatically.
solar_host_explain_refusal() {
  local stop_script="$_HOST_LIB_DIR/stop_host.sh" check_script="$_HOST_LIB_DIR/check_host.sh"
  echo "ERROR: the console on ${SOLAR_APP_HOST}:${SOLAR_APP_PORT} is not this workspace's console: ${HOST_REASON}." >&2
  echo "  expected workspace: ${SOLAR_WORKSPACE}" >&2
  if [[ -n "${HOST_OBSERVED_WORKSPACE:-}${HOST_OBSERVED_RUNTIME:-}" ]]; then
    echo "  console workspace:  ${HOST_OBSERVED_WORKSPACE:-<not reported>}" >&2
    echo "  console runtime:    ${HOST_OBSERVED_RUNTIME:-<not reported>}" >&2
  fi
  echo "  It was NOT reused and NOT stopped. Whoever owns it removes it, by hand:" >&2
  echo "    1. confirm what it serves:  bash '$check_script' --json" >&2
  echo "    2. as its owner (that workspace and runtime):  bash '$stop_script'" >&2
  echo "       or find its pid with  lsof -nP -iTCP:${SOLAR_APP_PORT} -sTCP:LISTEN  and stop it manually." >&2
  echo "  Automatic checks will not retry until it is gone." >&2
}

# Stops the listeners on the port that are provably this runtime's console and
# nothing else. Never stops a process that serves another identity, is not a
# host_server.py, or cannot be shown to be ours. Returns 0 only if one stopped.
solar_host_stop_orphan_listeners() {
  solar_host_load_env
  solar_host_assess
  local stopped=0 pid proof pidfile_pid candidates
  pidfile_pid="$(solar_host_pidfile_pid "$HOST_STATE" || true)"
  case "$HOST_STATE" in
    match|stale_workspace)
      # Identity belongs to the one process that answered, not to every listener.
      candidates="$HOST_OBSERVED_PID"
      if [[ -z "$candidates" ]]; then
        # A console that reports no pid: the listener on exactly our address.
        candidates="$(solar_host_port_listener_pids)"
      elif ! solar_host_reported_pid_is_listener "$candidates"; then
        # The reported pid must really be the listener of this address.
        echo "WARN: pid $candidates reported by the console is not its listener on ${SOLAR_APP_HOST}:${SOLAR_APP_PORT}; left untouched" >&2
        candidates=""
      fi
      ;;
    *)
      candidates="$(solar_host_port_listener_pids)"
      ;;
  esac
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if ! solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: listener pid $pid on :$SOLAR_APP_PORT is not a Solar console; left untouched" >&2
      continue
    fi
    proof=""
    case "$HOST_STATE" in
      match) proof="identity" ;;
      stale_workspace) proof="pid file and identity" ;;
      mismatch|invalid) ;;
      *)
        if [[ "$pid" == "$pidfile_pid" ]]; then
          proof="pid file"
        elif solar_host_pid_is_this_install "$pid"; then
          proof="install path"
        fi
        ;;
    esac
    if [[ -z "$proof" ]]; then
      echo "WARN: listener pid $pid on :$SOLAR_APP_PORT is not provably this runtime's console (${HOST_REASON}); left untouched" >&2
      continue
    fi
    echo "WARN: stopping Solar Host listener (pid $pid on :$SOLAR_APP_PORT, ownership: $proof)" >&2
    solar_host_stop_pid "$pid" && stopped=1
  done <<<"$candidates"
  [[ "$stopped" -eq 1 ]]
}
