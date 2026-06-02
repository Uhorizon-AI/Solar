#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_paths.sh
source "$SCRIPT_DIR/resolve_solar_paths.sh"
solar_resolve_paths --quiet
SOLAR_WORKSPACE="$SOLAR_WORKSPACE"
cd "$SOLAR_WORKSPACE"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

SOLAR_INTERFACE_HOST="${SOLAR_INTERFACE_HOST:-127.0.0.1}"
SOLAR_INTERFACE_PORT="${SOLAR_INTERFACE_PORT:-7741}"
SOLAR_INTERFACE_RUNTIME_DIR="${SOLAR_INTERFACE_RUNTIME_DIR:-sun/runtime/app}"
SOLAR_INTERFACE_RUNTIME_DIR_ABS="$SOLAR_WORKSPACE/${SOLAR_INTERFACE_RUNTIME_DIR#./}"
SOLAR_INTERFACE_DB_DIR="$SOLAR_INTERFACE_RUNTIME_DIR_ABS/db"
SOLAR_INTERFACE_MIGRATIONS_DIR="$SOLAR_INTERFACE_DB_DIR/migrations"
SOLAR_INTERFACE_STATE_DIR="$SOLAR_INTERFACE_RUNTIME_DIR_ABS/state"
SOLAR_INTERFACE_THREADS_DIR="$SOLAR_INTERFACE_RUNTIME_DIR_ABS/threads"
SOLAR_INTERFACE_RUNS_DIR="$SOLAR_INTERFACE_RUNTIME_DIR_ABS/runs"
SOLAR_INTERFACE_LOGS_DIR="$SOLAR_INTERFACE_RUNTIME_DIR_ABS/logs"
SOLAR_INTERFACE_DB_PATH="$SOLAR_INTERFACE_DB_DIR/interface.sqlite"
SOLAR_INTERFACE_PID_FILE="$SOLAR_INTERFACE_STATE_DIR/interface.pid"
SOLAR_INTERFACE_CURRENT_THREAD_FILE="$SOLAR_INTERFACE_STATE_DIR/current-thread.json"
SOLAR_INTERFACE_STDOUT_LOG="$SOLAR_INTERFACE_LOGS_DIR/interface.stdout.log"
SOLAR_INTERFACE_STDERR_LOG="$SOLAR_INTERFACE_LOGS_DIR/interface.stderr.log"
SOLAR_INTERFACE_BASE_URL="http://${SOLAR_INTERFACE_HOST}:${SOLAR_INTERFACE_PORT}"

ensure_interface_dirs() {
  mkdir -p \
    "$SOLAR_INTERFACE_DB_DIR" \
    "$SOLAR_INTERFACE_MIGRATIONS_DIR" \
    "$SOLAR_INTERFACE_STATE_DIR" \
    "$SOLAR_INTERFACE_THREADS_DIR" \
    "$SOLAR_INTERFACE_RUNS_DIR" \
    "$SOLAR_INTERFACE_LOGS_DIR"
}

is_interface_pid_alive() {
  if [[ ! -f "$SOLAR_INTERFACE_PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$SOLAR_INTERFACE_PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

get_interface_listener_pid() {
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -ti "tcp:${SOLAR_INTERFACE_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1
}

is_interface_server_pid() {
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 1
  local cmd
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$cmd" == *"core/skills/solar-interface/scripts/interface_server.py"* ]]
}
