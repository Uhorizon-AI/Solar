#!/usr/bin/env bash
# host_lib.sh — Solar Host paths and API base URL.
set -euo pipefail

_HOST_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CLIENT_SCRIPTS="$(cd "$_HOST_LIB_DIR/../../solar-client/scripts" && pwd)"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$_CLIENT_SCRIPTS/resolve_solar_paths.sh"
# shellcheck source=host_env_compat.sh
source "$_HOST_LIB_DIR/host_env_compat.sh"

solar_host_workspace_ports() {
  local ws="$1"
  python3 "$_HOST_LIB_DIR/host_registry.py" ports "$ws"
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
  if [[ -z "${SOLAR_APP_PORT:-}" || -z "${SOLAR_HTTP_PORT:-}" ]]; then
    read -r _host_port _gw < <(solar_host_workspace_ports "$SOLAR_WORKSPACE")
    if [[ -z "${SOLAR_APP_PORT:-}" ]]; then
      export SOLAR_APP_PORT="${_host_port:-9000}"
    fi
    if [[ -z "${SOLAR_HTTP_PORT:-}" ]]; then
      export SOLAR_HTTP_PORT="${_gw:-8787}"
    fi
  fi
  export SOLAR_APP_HOST="${SOLAR_APP_HOST:-127.0.0.1}"
  export SOLAR_APP_PORT="${SOLAR_APP_PORT:-9000}"
  export SOLAR_APP_BASE_URL="http://${SOLAR_APP_HOST}:${SOLAR_APP_PORT}"
  export SOLAR_HOST_RUNTIME_DIR="${SOLAR_HOST_RUNTIME_DIR:-sun/runtime/host}"
  export SOLAR_HOST_PID_FILE="$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR/host.pid"
}

solar_host_runtime_dir() {
  solar_host_load_env
  mkdir -p "$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR"
  printf '%s\n' "$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR"
}

# PIDs listening on SOLAR_APP_HOST:SOLAR_APP_PORT (orphan recovery when host.pid is missing).
solar_host_port_listener_pids() {
  solar_host_load_env
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  lsof -nP -iTCP:"$SOLAR_APP_PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
}

solar_host_pid_looks_like_server() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" -o args= 2>/dev/null | grep -q 'host_server\.py'
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

# Stop listeners that look like host_server.py (no pid file).
solar_host_stop_orphan_listeners() {
  solar_host_load_env
  local stopped=0
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: stopping orphan Solar Host listener (pid $pid on :$SOLAR_APP_PORT)" >&2
      solar_host_stop_pid "$pid"
      stopped=1
    fi
  done < <(solar_host_port_listener_pids)
  [[ "$stopped" -eq 1 ]]
}
