#!/usr/bin/env bash
# host_lib.sh — Solar Host paths and interface API base URL.
set -euo pipefail

_HOST_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_INTERFACE_SCRIPTS="$(cd "$_HOST_LIB_DIR/../../solar-interface/scripts" && pwd)"
# shellcheck source=resolve_solar_paths.sh
source "$_INTERFACE_SCRIPTS/resolve_solar_paths.sh"

solar_host_load_env() {
  solar_resolve_paths --quiet
  if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SOLAR_WORKSPACE/.env"
    set +a
  fi
  export SOLAR_HOST_HOST="${SOLAR_HOST_HOST:-127.0.0.1}"
  export SOLAR_HOST_PORT="${SOLAR_HOST_PORT:-9000}"
  export SOLAR_INTERFACE_HOST="${SOLAR_INTERFACE_HOST:-127.0.0.1}"
  export SOLAR_INTERFACE_PORT="${SOLAR_INTERFACE_PORT:-7741}"
  export SOLAR_HOST_BASE_URL="http://${SOLAR_HOST_HOST}:${SOLAR_HOST_PORT}"
  export SOLAR_INTERFACE_BASE_URL="http://${SOLAR_INTERFACE_HOST}:${SOLAR_INTERFACE_PORT}"
  export SOLAR_HOST_RUNTIME_DIR="${SOLAR_HOST_RUNTIME_DIR:-sun/runtime/host}"
  export SOLAR_HOST_PID_FILE="$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR/host.pid"
}

solar_host_runtime_dir() {
  solar_host_load_env
  mkdir -p "$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR"
  printf '%s\n' "$SOLAR_WORKSPACE/$SOLAR_HOST_RUNTIME_DIR"
}
