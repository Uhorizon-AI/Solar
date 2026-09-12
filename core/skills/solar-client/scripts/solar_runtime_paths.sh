#!/usr/bin/env bash
# solar_runtime_paths.sh — machine-state homes outside the workspace.
#
# Framework runtime: $SOLAR_RUNTIME_ROOT, else <app data>/Solar/runtime.
# Planet state:      <app data>/Solar/planets/<bucket>/<skill>.
#
# Identity is computed on the physical resolved path, never on the string
# received. There is no silent fallback to sun/runtime.
#
# Usage: source this file, then call solar_runtime_root / solar_runtime_dir /
# solar_planet_state_dir.

_solar_runtime_scripts_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

# expanduser + realpath, tolerating a not-yet-created tail.
solar_canonical_path() {
  local raw="${1:?path required}"
  case "$raw" in
    "~") raw="$HOME" ;;
    "~/"*) raw="$HOME/${raw#\~/}" ;;
  esac
  python3 -c 'import sys,pathlib;print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$raw"
}

solar_app_data_dir() {
  if [[ -n "${SOLAR_APP_DATA:-}" ]]; then
    solar_canonical_path "$SOLAR_APP_DATA"
    return 0
  fi
  case "$(uname -s)" in
    Darwin) solar_canonical_path "$HOME/Library/Application Support" ;;
    *)
      if [[ -n "${XDG_DATA_HOME:-}" ]]; then
        solar_canonical_path "$XDG_DATA_HOME"
      else
        solar_canonical_path "$HOME/.local/share"
      fi
      ;;
  esac
}

solar_global_dir() {
  printf '%s/Solar\n' "$(solar_app_data_dir)"
}

solar_runtime_root() {
  if [[ -n "${SOLAR_RUNTIME_ROOT:-}" ]]; then
    solar_canonical_path "$SOLAR_RUNTIME_ROOT"
    return 0
  fi
  printf '%s/runtime\n' "$(solar_global_dir)"
}

# solar_runtime_dir <subpath...> [--create]
solar_runtime_dir() {
  local create=0 parts=()
  for arg in "$@"; do
    if [[ "$arg" == "--create" ]]; then create=1; else parts+=("$arg"); fi
  done
  local path
  path="$(solar_runtime_root)"
  local part
  for part in ${parts[@]+"${parts[@]}"}; do
    path="$path/$part"
  done
  [[ "$create" -eq 1 ]] && mkdir -p "$path"
  printf '%s\n' "$path"
}

# solar_planet_state_dir <planet_path> <skill> [--create]
solar_planet_state_dir() {
  local planet_path="${1:?planet path required}"
  local skill="${2:?skill required}"
  shift 2
  local extra=()
  [[ "${1:-}" == "--create" ]] && extra+=(--create)
  python3 "$(_solar_runtime_scripts_dir)/solar_runtime.py" planet \
    "$planet_path" "$skill" ${extra[@]+"${extra[@]}"}
}
