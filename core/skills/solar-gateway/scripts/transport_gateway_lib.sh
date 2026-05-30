#!/usr/bin/env bash
# transport_gateway_lib.sh — workspace + SOLAR_ROOT for transport-gateway scripts.
set -euo pipefail

_TGW_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_RESOLVE_SCRIPT="$_TGW_LIB_DIR/../../solar-interface/scripts/resolve_solar_paths.sh"

transport_gateway_bind_workspace() {
  if [[ -n "${_TGW_BOUND:-}" ]]; then
    return 0
  fi
  # shellcheck source=/dev/null
  source "$_RESOLVE_SCRIPT"
  solar_resolve_paths --quiet
  cd "$SOLAR_WORKSPACE"
  if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SOLAR_WORKSPACE/.env"
    set +a
  fi
  _TGW_BOUND=1
}

transport_gateway_script() {
  local name="$1"
  transport_gateway_bind_workspace
  printf '%s/skills/solar-gateway/scripts/%s' "$(solar_core_dir)" "$name"
}
