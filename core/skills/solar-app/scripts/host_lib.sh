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
# overrides removed), compared on physical paths. The answer is cached in the
# process: each call shells out twice, and helpers call it repeatedly.
_solar_host_temp_runtime=""
solar_host_runtime_is_temporary() {
  if [[ -n "${_solar_host_temp_runtime:-}" ]]; then
    [[ "$_solar_host_temp_runtime" == yes ]]
    return
  fi
  local live resolved py
  py="$(cd "$_PATHS_SCRIPTS" && pwd)/solar_runtime.py"
  if [[ ! -f "$py" ]]; then
    _solar_host_temp_runtime="no"
    return 1
  fi
  if ! live="$(env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA python3 "$py" runtime 2>/dev/null)"; then
    _solar_host_temp_runtime="no"
    return 1
  fi
  if ! resolved="$(python3 "$py" runtime 2>/dev/null)"; then
    _solar_host_temp_runtime="no"
    return 1
  fi
  live="$(solar_canonical_path "$live")"
  resolved="$(solar_canonical_path "$resolved")"
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

# The install this runtime was started from, as physical paths. Two layouts are
# possible: the published framework checkout (core/skills/solar-app inside a
# solar install, two levels up) and a workspace mirror where solar-app sits one
# level above core/skills/solar-app. Both are returned so the check works in
# either layout; everything else resolves to a non-existing path and is skipped.
# Stable across the check: it depends only on the script location, not on the
# environment.
solar_host_identity_install_roots() {
  printf '%s\n' "$(cd "$_HOST_LIB_DIR/../../.." && pwd -P)"
  printf '%s\n' "$(cd "$_HOST_LIB_DIR/../../../.." && pwd -P)"
}

# The single identity policy lives in host_identity.py. Everything here calls
# it, so no reuse path can drift: /health must report this runtime's workspace
# and runtime, and a console that reports no identity — or only half of it — is
# adopted only with a proof that the process is ours (this runtime's pid file or
# this install's host_server.py in the listener command).
solar_host_identity_own() {
  local health_file="$1"
  local pid_file="${2-}"
  local listener_pid="${3-}"
  local -a roots=()
  while IFS= read -r root; do
    [[ -n "$root" ]] && roots+=(--install-root "$root")
  done < <(solar_host_identity_install_roots)
  python3 "$_HOST_LIB_DIR/host_identity.py" evaluate \
    --health-file "$health_file" \
    --workspace "$(solar_host_identity_workspace)" \
    --runtime "$(solar_host_identity_runtime)" \
    --pid-file "$pid_file" \
    --listener-pid "$listener_pid" \
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
solar_host_listener_identity() {
  solar_host_load_env
  local pid="${1-}" health_file listener_command status
  [[ -n "$pid" ]] || pid="$(solar_host_port_listener_pids | head -n1 || true)"
  listener_command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  health_file="$(mktemp "${TMPDIR:-/tmp}/solar-host-health.XXXXXX")"
  if ! python3 - "$SOLAR_APP_BASE_URL" "$health_file" <<'PY'
import json, sys, urllib.request
base, dest = sys.argv[1:3]
try:
    with urllib.request.urlopen(base + "/health", timeout=3) as response:
        data = json.load(response)
except Exception:
    raise SystemExit(1)
with open(dest, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
  then
    # No answer: not ours only when the command line is some other install's.
    if solar_host_command_is_install_server "$listener_command"; then
      echo own
    else
      echo unproven
    fi
    rm -f "$health_file"
    return 0
  fi
  set +e
  solar_host_identity_own "$health_file" "$SOLAR_HOST_PID_FILE" "$pid" >/dev/null 2>&1
  status=$?
  set -e
  rm -f "$health_file"
  if [[ "$status" -eq 0 ]]; then
    echo own
  else
    echo foreign
  fi
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
  # One definition of "runs host_server.py": the same check the identity engine
  # uses, so this and pid-file ownership cannot drift apart.
  solar_host_command_looks_like_server "$(ps -p "$pid" -o args= 2>/dev/null || true)"
}

# True when a command line names host_server.py at all (no install check: the
# install check is command_is_install_server in host_identity.py).
solar_host_command_looks_like_server() {
  [[ "$1" == *host_server.py* ]]
}

# True when the pid file at $1 (default: this runtime's own) names a live
# host_server.py process. A pid that was reused by another program is not ours,
# and the argument is the path of the pid file, never the pid value itself.
solar_host_pid_file_is_own_server() {
  local pid_file="${1:-$SOLAR_HOST_PID_FILE}"
  [[ -f "$pid_file" ]] || return 1
  python3 "$_HOST_LIB_DIR/host_identity.py" pid-file-is-own-server --pid-file "$pid_file"
}

# Human-readable owner of the port. Never stops anything.
solar_host_report_foreign_listener() {
  solar_host_load_env
  local pid="${1-}" args
  [[ -n "$pid" ]] || pid="$(solar_host_port_listener_pids | head -n1 || true)"
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

# Stop listeners of the port only when they are this runtime's own console.
# "Own" means the /health payload names this workspace and runtime, or — for a
# console that reports no identity — a proof that the process is ours (this
# install's host_server.py in its command line). Anything else, including a
# listener that cannot be proven either way, is reported and left running.
#
# Return contract: 0 when at least one own listener was stopped, 1 when the port
# had none (or none was own), 2 when a listener was foreign. A foreign listener
# anywhere in the list wins over having stopped another one, because the caller
# must not report a clean stop while a foreign console still holds the port.
solar_host_stop_orphan_listeners() {
  solar_host_load_env
  local stopped=0 foreign=0
  local pid identity
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    identity="$(solar_host_listener_identity "$pid")"
    if [[ "$identity" == own ]] && solar_host_pid_looks_like_server "$pid"; then
      echo "WARN: stopping orphan Solar Host listener (pid $pid on :$SOLAR_APP_PORT)" >&2
      solar_host_stop_pid "$pid"
      stopped=1
      continue
    fi
    if [[ "$identity" == own ]]; then
      # Ours by identity, but its command line is not host_server.py: do not kill
      # it and do not label it foreign. Report the concrete reason and move on.
      echo "WARN: listener pid $pid on :$SOLAR_APP_PORT is ours by identity but is not host_server.py — leaving it running" >&2
      continue
    fi
    solar_host_report_foreign_listener "$pid"
    foreign=1
  done < <(solar_host_port_listener_pids)
  [[ "$foreign" -eq 1 ]] && return 2
  [[ "$stopped" -eq 1 ]]
}

# Guard for the reuse path: when something holds the console port and it is not
# this runtime's own console, report it and return 3. Retrying cannot converge,
# so every caller (start_host.sh, ensure_host.sh) stops here with the same
# message. An own hung console (this install's host_server.py in its command
# line) is not this case: it returns 0 and the caller may recover it. Returns 0 —
# and does nothing — when the port is free or the listener is provably ours.
solar_host_refuse_foreign_listener() {
  solar_host_load_env
  solar_host_port_listener_pids | grep -q . || return 0
  local identity
  identity="$(solar_host_listener_identity)"
  if [[ "$identity" != own ]]; then
    solar_host_report_foreign_listener
    return 3
  fi
  return 0
}
