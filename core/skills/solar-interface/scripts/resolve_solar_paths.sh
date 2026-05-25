#!/usr/bin/env bash
# resolve_solar_paths.sh — Solar workspace + install root resolution.
# Source and call: solar_resolve_paths [--workspace <path>] [--quiet] [--export] [--relaxed]
# Exports: SOLAR_WORKSPACE, SOLAR_ROOT (install root; core/ lives at $SOLAR_ROOT/core)
set -euo pipefail

_RESOLVE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_RESOLVE_QUIET=false
_RESOLVE_EXPORT=false
_RESOLVE_RELAXED=false
_RESOLVE_FORCE_WORKSPACE=""

_resolve_usage() {
  cat <<'EOF'
Usage (source this file):
  source resolve_solar_paths.sh
  solar_resolve_paths [--workspace <path>] [--quiet] [--export] [--relaxed]

Exports on success:
  SOLAR_WORKSPACE   Active agent (sun/, planets/, .env, .solar/manifest.json)
  SOLAR_ROOT        Solar install root (always contains core/)

Helper (after resolve):
  solar_core_dir    Prints $SOLAR_ROOT/core

Exit codes:
  0  success
  1  no workspace / conflict / invalid path / obsolete .solar/core/
EOF
}

solar_core_dir() {
  [[ -n "${SOLAR_ROOT:-}" ]] || {
    echo "ERROR: SOLAR_ROOT not set (run solar_resolve_paths first)" >&2
    return 1
  }
  printf '%s/core' "$SOLAR_ROOT"
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

_resolve_validate_root() {
  local root="$1"
  [[ -f "$root/core/skills/solar-interface/scripts/solar" ]]
}

_resolve_global_root() {
  if [[ -n "${SOLAR_ROOT:-}" ]]; then
    local existing
    existing="$(_resolve_abs "$SOLAR_ROOT")" || return 1
    if _resolve_validate_root "$existing"; then
      echo "$existing"
      return 0
    fi
  fi
  local bundled
  bundled="$(_resolve_abs "$_RESOLVE_SCRIPT_DIR/../../../..")"
  if _resolve_validate_root "$bundled"; then
    echo "$bundled"
    return 0
  fi
  echo "ERROR: Solar install not found (set SOLAR_ROOT or install solar CLI)" >&2
  return 1
}

_resolve_discover_manifest_workspace() {
  local dir
  dir="$(pwd -P)"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.solar/manifest.json" && -d "$dir/sun" ]]; then
      _resolve_abs "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

_resolve_discover_legacy_root() {
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

_resolve_discover_legacy_solar_subtree() {
  local dir
  dir="$(pwd -P)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/solar/core" && -f "$dir/solar/core/AGENTS.md" && -d "$dir/sun" ]]; then
      _resolve_abs "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

_resolve_discover() {
  local found=""
  if found="$(_resolve_discover_manifest_workspace 2>/dev/null)"; then
    echo "$found"
    return 0
  fi
  if found="$(_resolve_discover_legacy_root 2>/dev/null)"; then
    echo "$found"
    return 0
  fi
  if found="$(_resolve_discover_legacy_solar_subtree 2>/dev/null)"; then
    echo "$found"
    return 0
  fi
  return 1
}

_resolve_workspace_layout() {
  local ws="$1"
  if [[ -f "$ws/.solar/manifest.json" ]]; then
    echo "client"
    return 0
  fi
  if [[ -d "$ws/solar/core" && -f "$ws/solar/core/AGENTS.md" ]]; then
    echo "legacy_solar"
    return 0
  fi
  if [[ -d "$ws/core" && -f "$ws/core/AGENTS.md" ]]; then
    echo "legacy_root"
    return 0
  fi
  return 1
}

_resolve_fail_obsolete_core() {
  _resolve_fail "obsolete .solar/core/ at $1 — run: solar client upgrade"
  return 1
}

_resolve_set_paths() {
  local ws="$1"
  local layout=""

  if [[ "$_RESOLVE_RELAXED" != true && -d "$ws/.solar/core" ]]; then
    _resolve_fail_obsolete_core "$ws"
    return 1
  fi

  layout="$(_resolve_workspace_layout "$ws")" || {
    echo "ERROR: invalid Solar workspace at $ws (need manifest+sun/, legacy core/, or solar/core/)" >&2
    return 1
  }

  export SOLAR_WORKSPACE="$ws"

  case "$layout" in
    client)
      SOLAR_ROOT="$(_resolve_global_root)" || return 1
      export SOLAR_ROOT
      ;;
    legacy_solar)
      export SOLAR_ROOT="$(_resolve_abs "$ws/solar")"
      ;;
    legacy_root)
      export SOLAR_ROOT="$(_resolve_abs "$ws")"
      ;;
    *)
      echo "ERROR: unknown workspace layout: $layout" >&2
      return 1
      ;;
  esac
  return 0
}

_resolve_fail() {
  echo "ERROR: $1" >&2
  return 1
}

_resolve_emit() {
  if [[ "$_RESOLVE_EXPORT" == true ]]; then
    echo "SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
    echo "SOLAR_ROOT=$SOLAR_ROOT"
  elif [[ "$_RESOLVE_QUIET" != true ]]; then
    echo "SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
    echo "SOLAR_ROOT=$SOLAR_ROOT"
  fi
}

solar_resolve_paths() {
  local discovery=""
  local exported=""
  local resolved=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --workspace|--home)
        shift
        [[ $# -gt 0 ]] || { _resolve_fail "missing value for --workspace"; return 1; }
        _RESOLVE_FORCE_WORKSPACE="$1"
        shift
        ;;
      --quiet) _RESOLVE_QUIET=true; shift ;;
      --export) _RESOLVE_EXPORT=true; _RESOLVE_QUIET=true; shift ;;
      --relaxed) _RESOLVE_RELAXED=true; shift ;;
      -h|--help) _resolve_usage; return 0 ;;
      *) _resolve_fail "unknown option: $1"; return 1 ;;
    esac
  done

  if [[ -n "$_RESOLVE_FORCE_WORKSPACE" ]]; then
    local forced
    forced="$(_resolve_abs "$_RESOLVE_FORCE_WORKSPACE")" || {
      _resolve_fail "invalid path for --workspace: $_RESOLVE_FORCE_WORKSPACE"
      return 1
    }
    if [[ ! -d "$forced" ]]; then
      _resolve_fail "path does not exist: $forced"
      return 1
    fi
    _resolve_set_paths "$forced" || return 1
    _resolve_emit
    return 0
  fi

  if discovery="$(_resolve_discover 2>/dev/null)"; then
    :
  else
    discovery=""
  fi

  if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
    exported="$(_resolve_abs "$SOLAR_WORKSPACE")" || exported=""
  fi

  if [[ -n "$discovery" && -n "$exported" && "$discovery" != "$exported" ]]; then
    _resolve_fail "SOLAR_WORKSPACE conflict: exported=$exported discovery=$discovery (use --workspace)"
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
      _resolve_fail "SOLAR_WORKSPACE=$exported but cwd=$pwd_abs is outside that tree (use --workspace)"
      return 1
    fi
  else
    _resolve_fail "no Solar workspace found (ancestors of $(pwd))"
    return 1
  fi

  _resolve_set_paths "$resolved" || return 1
  _resolve_emit
  return 0
}
