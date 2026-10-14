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
  SOLAR_APP_PORT="$(python3 "$_HOST_LIB_DIR/host_identity.py" port)"
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

# PIDs listening on a LOOPBACK address of SOLAR_APP_PORT. Empty without lsof: no
# caller may then adopt or stop an unidentified console. Listeners on another
# address (LAN or wildcard) are not this console and are never returned.
solar_host_port_listener_pids() {
  solar_host_load_env
  python3 "$_HOST_LIB_DIR/host_identity.py" listeners "$SOLAR_APP_PORT"
}

# Sets HOST_STATE, HOST_REASON, HOST_OBSERVED_WORKSPACE, HOST_OBSERVED_RUNTIME.
# Requires solar_host_load_env. Never exits non-zero.
solar_host_assess() {
  local line
  line="$(python3 "$_HOST_LIB_DIR/host_identity.py" assess --base-url "$SOLAR_APP_BASE_URL" \
    --workspace "$SOLAR_WORKSPACE" 2>/dev/null || true)"
  IFS=$'\t' read -r HOST_STATE HOST_REASON HOST_OBSERVED_WORKSPACE HOST_OBSERVED_RUNTIME <<<"$line" || true
  HOST_STATE="${HOST_STATE:-unreachable}"
  HOST_REASON="${HOST_REASON:-console unreachable}"
}

solar_host_pid_looks_like_server() {
  local pid="$1" args
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  args="$(ps -p "$pid" -o args= 2>/dev/null)" || return 1
  [[ "$args" =~ (^|[[:space:]/])host_server\.py($|[[:space:]]) ]]
}

# True when the process runs THIS install's host_server.py. Compared as the path
# the library was loaded from and as its physical path (symlinked installs).
solar_host_pid_is_this_install() {
  local pid="$1" args script real
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  args="$(ps -p "$pid" -o args= 2>/dev/null)" || return 1
  for script in "$_HOST_LIB_DIR/host_server.py" "$(cd -P "$_HOST_LIB_DIR" && pwd -P)/host_server.py"; do
    [[ "$args" == *"$script" || "$args" == *"$script "* ]] && return 0
  done
  return 1
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
    match|legacy|partial)
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
  echo "ERROR: the console on 127.0.0.1:${SOLAR_APP_PORT} is not this workspace's console: ${HOST_REASON}." >&2
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
  local stopped=0 pid proof pidfile_pid
  pidfile_pid="$(solar_host_pidfile_pid "$HOST_STATE" || true)"
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if ! solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: listener pid $pid on :$SOLAR_APP_PORT is not a Solar console; left untouched" >&2
      continue
    fi
    proof=""
    case "$HOST_STATE" in
      match) proof="identity" ;;
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
  done < <(solar_host_port_listener_pids)
  [[ "$stopped" -eq 1 ]]
}
