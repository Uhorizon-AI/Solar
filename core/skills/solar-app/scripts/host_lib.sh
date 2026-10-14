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
  # The console port is fixed at 9000. SOLAR_APP_PORT_OVERRIDE exists only so a
  # test can keep its stub off the machine's real console port.
  export SOLAR_APP_PORT="${SOLAR_APP_PORT_OVERRIDE:-9000}"
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

# True when this runtime's own pid file names a live host_server.py process.
# A pid that was reused by another program is not ours.
solar_host_pid_file_is_own_server() {
  local pid
  [[ -f "$SOLAR_HOST_PID_FILE" ]] || return 1
  pid="$(cat "$SOLAR_HOST_PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  solar_host_pid_looks_like_server "$pid"
}

# True when the console on SOLAR_APP_BASE_URL answers /health with this
# runtime's workspace and runtime. A console that reports no identity is not
# treated as ours.
solar_host_listener_identity_matches() {
  python3 - "$SOLAR_APP_BASE_URL" "$(solar_host_identity_workspace)" "$(solar_host_identity_runtime)" <<'PY'
import json, sys, urllib.request
from pathlib import Path
base, want_ws, want_rt = sys.argv[1:4]
try:
    with urllib.request.urlopen(base + "/health", timeout=3) as response:
        data = json.load(response)
except Exception:
    sys.exit(1)
got_ws = str(data.get("workspace") or "")
got_rt = str(data.get("runtime") or "")
if not got_ws or not got_rt:
    sys.exit(1)
canon = lambda p: str(Path(p).expanduser().resolve())
sys.exit(0 if canon(got_ws) == canon(want_ws) and canon(got_rt) == canon(want_rt) else 1)
PY
}

# Human-readable owner of the port. Never stops anything.
solar_host_report_foreign_listener() {
  solar_host_load_env
  local pid args
  pid="$(solar_host_port_listener_pids | head -n1 || true)"
  [[ -n "$pid" ]] || return 0
  args="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  {
    echo "ERROR: :$SOLAR_APP_PORT is held by pid $pid, which is not the console of this runtime."
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

# Stop listeners of the port only when they are this runtime's own console
# (they look like host_server.py AND /health reports this workspace and
# runtime). Anything else is a foreign console: report it and return 2 without
# killing it. Returns 0 when it stopped a listener, 1 when the port had none.
solar_host_stop_orphan_listeners() {
  solar_host_load_env
  local stopped=0
  local pid
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if solar_host_pid_looks_like_server "$pid" && solar_host_listener_identity_matches; then
      echo "WARN: stopping orphan Solar Host listener (pid $pid on :$SOLAR_APP_PORT)" >&2
      solar_host_stop_pid "$pid"
      stopped=1
      continue
    fi
    solar_host_report_foreign_listener
    return 2
  done < <(solar_host_port_listener_pids)
  [[ "$stopped" -eq 1 ]]
}
