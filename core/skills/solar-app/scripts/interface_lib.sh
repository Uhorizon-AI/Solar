#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CLIENT_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-client/scripts" && pwd)"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$_CLIENT_SCRIPTS/resolve_solar_paths.sh"
solar_resolve_paths --quiet
SOLAR_WORKSPACE="$SOLAR_WORKSPACE"
cd "$SOLAR_WORKSPACE"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

# shellcheck source=host_env_compat.sh
source "$SCRIPT_DIR/host_env_compat.sh"
solar_app_apply_legacy_env

SOLAR_APP_HOST="${SOLAR_APP_HOST:-127.0.0.1}"
SOLAR_APP_PORT="${SOLAR_APP_PORT:-9000}"
SOLAR_APP_BASE_URL="${SOLAR_APP_BASE_URL:-http://${SOLAR_APP_HOST}:${SOLAR_APP_PORT}}"
SOLAR_APP_RUNTIME_DIR="${SOLAR_APP_RUNTIME_DIR:-sun/runtime/app}"
SOLAR_APP_RUNTIME_DIR_ABS="$SOLAR_WORKSPACE/${SOLAR_APP_RUNTIME_DIR#./}"
SOLAR_APP_DB_DIR="$SOLAR_APP_RUNTIME_DIR_ABS/db"
SOLAR_APP_MIGRATIONS_DIR="$SOLAR_APP_DB_DIR/migrations"
SOLAR_APP_STATE_DIR="$SOLAR_APP_RUNTIME_DIR_ABS/state"
SOLAR_APP_THREADS_DIR="$SOLAR_APP_RUNTIME_DIR_ABS/threads"
SOLAR_APP_RUNS_DIR="$SOLAR_APP_RUNTIME_DIR_ABS/runs"
SOLAR_APP_LOGS_DIR="$SOLAR_APP_RUNTIME_DIR_ABS/logs"
SOLAR_APP_DB_PATH="$SOLAR_APP_DB_DIR/interface.sqlite"
SOLAR_APP_PID_FILE="$SOLAR_APP_STATE_DIR/app.pid"
SOLAR_APP_CURRENT_THREAD_FILE="$SOLAR_APP_STATE_DIR/current-thread.json"
SOLAR_APP_STDOUT_LOG="$SOLAR_APP_LOGS_DIR/app.stdout.log"
SOLAR_APP_STDERR_LOG="$SOLAR_APP_LOGS_DIR/app.stderr.log"

ensure_app_runtime_dirs() {
  mkdir -p \
    "$SOLAR_APP_DB_DIR" \
    "$SOLAR_APP_MIGRATIONS_DIR" \
    "$SOLAR_APP_STATE_DIR" \
    "$SOLAR_APP_THREADS_DIR" \
    "$SOLAR_APP_RUNS_DIR" \
    "$SOLAR_APP_LOGS_DIR"
}

# Backward-compatible alias (scripts sourcing interface_lib.sh).
ensure_interface_dirs() {
  ensure_app_runtime_dirs
}
