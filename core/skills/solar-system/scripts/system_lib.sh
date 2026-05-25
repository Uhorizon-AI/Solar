#!/usr/bin/env bash
# Shared path resolution for solar-system (source only).

_SOLAR_SYSTEM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_RESOLVE_SCRIPT="$_SOLAR_SYSTEM_LIB_DIR/../../solar-interface/scripts/resolve_solar_paths.sh"

solar_system_resolve_workspace() {
  if [[ -n "${_SOLAR_SYSTEM_RESOLVED:-}" ]]; then
    return 0
  fi
  # shellcheck source=/dev/null
  source "$_RESOLVE_SCRIPT"
  solar_resolve_paths --quiet
  _SOLAR_SYSTEM_RESOLVED=1
}

solar_system_bind_workspace() {
  solar_system_resolve_workspace
}

solar_system_workspace() {
  solar_system_resolve_workspace
  printf '%s\n' "$SOLAR_WORKSPACE"
}

solar_system_core_dir() {
  solar_system_resolve_workspace
  solar_core_dir
}

solar_system_load_env() {
  solar_system_resolve_workspace
  local env_file="${SOLAR_WORKSPACE}/.env"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$env_file"
    set +a
  fi
}

solar_system_runtime_dir() {
  solar_system_resolve_workspace
  local ws="${1:-$SOLAR_WORKSPACE}"
  local dir="${SOLAR_SYSTEM_RUNTIME_DIR:-sun/runtime/system}"
  if [[ "$dir" != /* ]]; then
    dir="$ws/$dir"
  fi
  printf '%s\n' "$dir"
}

solar_system_entrypoint() {
  printf '%s/Solar\n' "$(solar_system_runtime_dir "$1")"
}

solar_system_orchestrator_script() {
  solar_system_resolve_workspace
  printf '%s/skills/solar-system/scripts/run_orchestrator.sh\n' "$(solar_core_dir)"
}

solar_system_skill_script() {
  local skill="$1"
  local script="$2"
  solar_system_resolve_workspace
  printf '%s/skills/%s/scripts/%s\n' "$(solar_core_dir)" "$skill" "$script"
}

solar_system_suggest_script() {
  local rel="$1"
  case "$rel" in
    skills/*) ;;
    *) rel="skills/$rel" ;;
  esac
  solar_system_resolve_workspace
  printf '%s/%s' "$(solar_core_dir)" "$rel"
}
