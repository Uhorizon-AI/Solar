#!/usr/bin/env bash
# resolve_solar_paths.sh — Solar workspace + install root resolution.
# Source and call: solar_resolve_paths [--workspace <path>] [--quiet] [--export] [--relaxed]
# Exports: SOLAR_WORKSPACE, SOLAR_ROOT (runtime root; may be .solar/bundle in portable mode)
#          SOLAR_GLOBAL_ROOT (framework git install when discoverable; optional in portable-only)
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
  SOLAR_WORKSPACE      Active agent (sun/, planets/, .env, .solar/manifest.json)
  SOLAR_ROOT             Runtime install root (global framework or .solar/bundle in portable mode)
  SOLAR_GLOBAL_ROOT      Global framework install when discoverable (optional)

Helper (after resolve):
  solar_core_dir         Active runtime core (bundle or $SOLAR_ROOT/core)
  solar_global_core_dir  Global framework core/ (for bundle create, snapshot_outdated)

Exit codes:
  0  success
  1  no workspace / conflict / invalid path / obsolete .solar/core/
EOF
}

solar_core_dir() {
  solar_runtime_core_dir
}

solar_runtime_core_dir() {
  [[ -n "${SOLAR_ROOT:-}" ]] || {
    echo "ERROR: SOLAR_ROOT not set (run solar_resolve_paths first)" >&2
    return 1
  }
  if [[ "${SOLAR_CORE_SOURCE:-global}" == "workspace-snapshot" ]]; then
    local bundle_core="${SOLAR_WORKSPACE:-}/.solar/bundle/core"
    if [[ -f "$bundle_core/skills/solar-interface/scripts/solar" ]]; then
      printf '%s' "$bundle_core"
      return 0
    fi
    echo "ERROR: workspace-snapshot declared but bundle invalid — run: solar client bundle create" >&2
    return 1
  fi
  printf '%s/core' "$SOLAR_ROOT"
}

_resolve_is_workspace_bundle_root() {
  local root="$1"
  local ws="$2"
  [[ -n "$root" && -n "$ws" ]] || return 1
  local r b
  r="$(_resolve_abs "$root" 2>/dev/null || echo "$root")"
  b="$(_resolve_abs "$ws/.solar/bundle" 2>/dev/null || echo "")"
  [[ -n "$b" && "$r" == "$b" ]]
}

solar_global_install_root() {
  if [[ -n "${SOLAR_GLOBAL_ROOT:-}" ]]; then
    printf '%s' "$SOLAR_GLOBAL_ROOT"
    return 0
  fi
  if [[ -n "${SOLAR_ROOT:-}" && -n "${SOLAR_WORKSPACE:-}" ]] \
    && ! _resolve_is_workspace_bundle_root "$SOLAR_ROOT" "$SOLAR_WORKSPACE" \
    && _resolve_validate_root "$(_resolve_abs "$SOLAR_ROOT")"; then
    printf '%s' "$(_resolve_abs "$SOLAR_ROOT")"
    return 0
  fi
  local saved_root="${SOLAR_ROOT:-}"
  if [[ -n "$saved_root" && -n "${SOLAR_WORKSPACE:-}" ]] \
    && _resolve_is_workspace_bundle_root "$saved_root" "$SOLAR_WORKSPACE"; then
    unset SOLAR_ROOT
  fi
  _resolve_global_root
}

solar_global_core_dir() {
  local root
  root="$(solar_global_install_root)" || return 1
  printf '%s/core' "$root"
}

_resolve_manifest_core_source() {
  local ws="$1"
  local manifest="$ws/.solar/manifest.json"
  [[ -f "$manifest" ]] || { echo "global"; return 0; }
  python3 - <<'PY' "$manifest" 2>/dev/null || echo "global"
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(json.load(fh).get("core_source", "global") or "global")
except Exception:
    print("global")
PY
}

_resolve_bundle_valid() {
  local ws="$1"
  local bundle_core="$ws/.solar/bundle/core"
  [[ -f "$bundle_core/skills/solar-client/scripts/resolve_solar_paths.sh" \
    && -f "$bundle_core/skills/solar-client/scripts/sync-clients.sh" \
    && -f "$ws/.solar/bundle/index.json" ]]
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
  export SOLAR_CORE_SOURCE="$(_resolve_manifest_core_source "$ws")"

  case "$layout" in
    client)
      local global_root=""
      if [[ -n "${SOLAR_ROOT:-}" ]]; then
        local r
        r="$(_resolve_abs "$SOLAR_ROOT")"
        if _resolve_validate_root "$r" && ! _resolve_is_workspace_bundle_root "$r" "$ws"; then
          global_root="$r"
        fi
      fi
      if [[ -z "$global_root" ]]; then
        local saved="${SOLAR_ROOT:-}"
        if [[ -n "$saved" ]] && _resolve_is_workspace_bundle_root "$saved" "$ws"; then
          unset SOLAR_ROOT
        fi
        global_root="$(_resolve_global_root 2>/dev/null || true)"
      fi
      if [[ -n "$global_root" ]]; then
        export SOLAR_GLOBAL_ROOT="$(_resolve_abs "$global_root")"
      else
        unset SOLAR_GLOBAL_ROOT
      fi
      if [[ "$SOLAR_CORE_SOURCE" == "workspace-snapshot" ]]; then
        if _resolve_bundle_valid "$ws"; then
          export SOLAR_ROOT="$(_resolve_abs "$ws/.solar/bundle")"
        else
          echo "ERROR: core_source=workspace-snapshot but bundle is missing or invalid" >&2
          echo "HINT: run solar client bundle create on the primary machine" >&2
          return 1
        fi
      else
        SOLAR_ROOT="${SOLAR_GLOBAL_ROOT:-}"
        SOLAR_ROOT="${SOLAR_ROOT:-$(_resolve_global_root)}"
        export SOLAR_ROOT
      fi
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
    [[ -n "${SOLAR_GLOBAL_ROOT:-}" ]] && echo "SOLAR_GLOBAL_ROOT=$SOLAR_GLOBAL_ROOT"
  elif [[ "$_RESOLVE_QUIET" != true ]]; then
    echo "SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
    echo "SOLAR_ROOT=$SOLAR_ROOT"
    [[ -n "${SOLAR_GLOBAL_ROOT:-}" ]] && echo "SOLAR_GLOBAL_ROOT=$SOLAR_GLOBAL_ROOT"
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
