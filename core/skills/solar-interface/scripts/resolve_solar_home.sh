#!/usr/bin/env bash
# resolve_solar_home.sh — canonical Solar workspace root resolution.
# Source and call: solar_resolve_home [--home <path>] [--quiet]
# Exports: SOLAR_HOME, SOLAR_CORE_ROOT, REPO_ROOT
set -euo pipefail

_RESOLVE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_RESOLVE_QUIET=false
_RESOLVE_EXPORT=false
_RESOLVE_FORCE_HOME=""

_resolve_usage() {
  cat <<'EOF'
Usage (source this file):
  source resolve_solar_home.sh
  solar_resolve_home [--home <path>] [--quiet] [--export]

Exports on success:
  SOLAR_HOME       Workspace root (.solar/ or legacy core/ parent)
  SOLAR_CORE_ROOT  $SOLAR_HOME/.solar/core or $SOLAR_HOME/core (legacy)
  REPO_ROOT        Alias of SOLAR_HOME

Exit codes:
  0  success
  1  no workspace / conflict / invalid --home
EOF
}

_resolve_abs() {
  local p="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$p"
  else
    (
      cd "$(dirname "$p")" 2>/dev/null || exit 1
      echo "$(pwd -P)/$(basename "$p")"
    )
  fi
}

_resolve_is_subpath() {
  local child="$1"
  local parent="$2"
  case "$child" in
    "$parent") return 0 ;;
    "$parent"/*) return 0 ;;
    *) return 1 ;;
  esac
}

_resolve_discover_dot_solar() {
  local dir
  dir="$(pwd -P)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.solar/core" && -d "$dir/sun" ]]; then
      _resolve_abs "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

_resolve_discover_legacy() {
  local dir
  dir="$(pwd -P)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/core" && -f "$dir/core/AGENTS.md" && -d "$dir/sun" ]]; then
      _resolve_abs "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

_resolve_discover() {
  local found=""
  if found="$(_resolve_discover_dot_solar 2>/dev/null)"; then
    echo "$found"
    return 0
  fi
  if found="$(_resolve_discover_legacy 2>/dev/null)"; then
    echo "$found"
    return 0
  fi
  return 1
}

_resolve_set_core_root() {
  local home="$1"
  if [[ -d "$home/.solar" ]]; then
    export SOLAR_CORE_ROOT="$home/.solar/core"
  elif [[ -d "$home/core" ]]; then
    export SOLAR_CORE_ROOT="$home/core"
  else
    echo "ERROR: workspace at $home has no .solar/ or core/" >&2
    return 1
  fi
  export SOLAR_HOME="$home"
  export REPO_ROOT="$home"
  return 0
}

_resolve_fail() {
  echo "ERROR: $1" >&2
  return 1
}

solar_resolve_home() {
  local discovery=""
  local exported=""
  local resolved=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --home)
        shift
        [[ $# -gt 0 ]] || { _resolve_fail "missing value for --home"; return 1; }
        _RESOLVE_FORCE_HOME="$1"
        shift
        ;;
      --quiet) _RESOLVE_QUIET=true; shift ;;
      --export) _RESOLVE_EXPORT=true; _RESOLVE_QUIET=true; shift ;;
      -h|--help) _resolve_usage; return 0 ;;
      *) _resolve_fail "unknown option: $1"; return 1 ;;
    esac
  done

  if [[ -n "$_RESOLVE_FORCE_HOME" ]]; then
    local forced
    forced="$(_resolve_abs "$_RESOLVE_FORCE_HOME")" || {
      _resolve_fail "invalid path for --home: $_RESOLVE_FORCE_HOME"
      return 1
    }
    if [[ ! -d "$forced" ]]; then
      _resolve_fail "path does not exist: $forced"
      return 1
    fi
    _resolve_set_core_root "$forced" || return 1
    if [[ "$_RESOLVE_EXPORT" == true ]]; then
      echo "SOLAR_HOME=$SOLAR_HOME"
      echo "SOLAR_CORE_ROOT=$SOLAR_CORE_ROOT"
      echo "REPO_ROOT=$REPO_ROOT"
    elif [[ "$_RESOLVE_QUIET" != true ]]; then
      echo "SOLAR_HOME=$SOLAR_HOME (forced)"
    fi
    return 0
  fi

  # Always run discovery from $PWD (never early-return on export alone).
  if discovery="$(_resolve_discover 2>/dev/null)"; then
    :
  else
    discovery=""
  fi

  if [[ -n "${SOLAR_HOME:-}" ]]; then
    exported="$(_resolve_abs "$SOLAR_HOME")" || exported=""
  else
    exported=""
  fi

  if [[ -n "$discovery" && -n "$exported" && "$discovery" != "$exported" ]]; then
    _resolve_fail "SOLAR_HOME conflict: exported=$exported discovery=$discovery (use --home to override)"
    return 1
  fi

  if [[ -n "$discovery" ]]; then
    resolved="$discovery"
  elif [[ -n "$exported" ]]; then
    local pwd_abs
    pwd_abs="$(_resolve_abs "$(pwd)")"
    if _resolve_is_subpath "$pwd_abs" "$exported"; then
      resolved="$exported"
    else
      _resolve_fail "SOLAR_HOME=$exported is set but cwd=$pwd_abs is outside that workspace (use --home)"
      return 1
    fi
  else
    _resolve_fail "no Solar workspace found (looked for .solar/ or legacy core/ in ancestors of $(pwd))"
    return 1
  fi

  _resolve_set_core_root "$resolved" || return 1
  if [[ "$_RESOLVE_EXPORT" == true ]]; then
    echo "SOLAR_HOME=$SOLAR_HOME"
    echo "SOLAR_CORE_ROOT=$SOLAR_CORE_ROOT"
    echo "REPO_ROOT=$REPO_ROOT"
  elif [[ "$_RESOLVE_QUIET" != true ]]; then
    echo "SOLAR_HOME=$SOLAR_HOME"
  fi
  return 0
}
