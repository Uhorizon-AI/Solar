#!/usr/bin/env bash
# Shared path resolution for solar-system (source only).

solar_system_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  (cd "$script_dir/../../../.." && pwd)
}

solar_system_load_env() {
  local repo_root="${1:-$(solar_system_repo_root)}"
  if [[ -f "$repo_root/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$repo_root/.env"
    set +a
  fi
}

solar_system_runtime_dir() {
  local repo_root="${1:-$(solar_system_repo_root)}"
  local dir="${SOLAR_SYSTEM_RUNTIME_DIR:-sun/runtime/system}"
  if [[ "$dir" != /* ]]; then
    dir="$repo_root/$dir"
  fi
  printf '%s\n' "$dir"
}

solar_system_entrypoint() {
  printf '%s/Solar\n' "$(solar_system_runtime_dir "$1")"
}

solar_system_orchestrator_script() {
  local repo_root="${1:-$(solar_system_repo_root)}"
  printf '%s/core/skills/solar-system/scripts/run_orchestrator.sh\n' "$repo_root"
}
