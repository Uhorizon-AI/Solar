#!/usr/bin/env bash
# Shared path resolution for solar-system (source only).

_SOLAR_SYSTEM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_RESOLVE_SCRIPT="$_SOLAR_SYSTEM_LIB_DIR/../../solar-client/scripts/resolve_solar_paths.sh"

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

# Normalize a path for equality checks (absolute; strip trailing slash except "/").
solar_system_norm_path() {
  local p="${1:-}"
  [[ -n "$p" ]] || return 1
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$p" 2>/dev/null && return 0
  fi
  # Fallback when python3 is unavailable (tests should still pass with python3).
  p="${p%/}"
  [[ -n "$p" ]] || p="/"
  printf '%s\n' "$p"
}

# Read LaunchAgent EnvironmentVariables.SOLAR_ROOT from a plist. Empty if missing.
solar_system_plist_solar_root() {
  local plist="${1:-}"
  [[ -n "$plist" && -f "$plist" ]] || return 1
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 1
  fi
  /usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:SOLAR_ROOT' "$plist" 2>/dev/null || true
}

# Classify LaunchAgent SOLAR_ROOT vs the resolved install root.
# Prints one status token on stdout:
#   ok | missing_key | root_missing | orchestrator_missing | router_missing | mismatch
# Args: $1=plist_root $2=expected_SOLAR_ROOT
solar_system_classify_plist_root() {
  local plist_root="${1:-}"
  local expected="${2:-}"
  local orch router norm_plist norm_expected

  if [[ -z "$plist_root" ]]; then
    echo "missing_key"
    return 0
  fi
  if [[ ! -d "$plist_root" ]]; then
    echo "root_missing"
    return 0
  fi

  orch="$plist_root/core/skills/solar-system/scripts/run_orchestrator.sh"
  router="$plist_root/core/skills/solar-router/scripts/run_router.py"
  if [[ ! -f "$orch" ]]; then
    echo "orchestrator_missing"
    return 0
  fi
  if [[ ! -f "$router" ]]; then
    echo "router_missing"
    return 0
  fi

  if [[ -n "$expected" ]]; then
    norm_plist="$(solar_system_norm_path "$plist_root" || true)"
    norm_expected="$(solar_system_norm_path "$expected" || true)"
    if [[ -n "$norm_plist" && -n "$norm_expected" && "$norm_plist" != "$norm_expected" ]]; then
      echo "mismatch"
      return 0
    fi
  fi

  echo "ok"
}

# Map classify status → check_orchestrator severity (HEALTHY|PARTIAL|DOWN).
solar_system_plist_root_severity() {
  case "${1:-}" in
    ok|skipped) echo "HEALTHY" ;;
    *) echo "DOWN" ;;
  esac
}
