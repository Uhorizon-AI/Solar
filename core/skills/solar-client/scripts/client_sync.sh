#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

usage_sync() {
  cat <<'EOF'
Usage:
  solar client sync [--portable] [sync-clients options]
  solar client sync exclude list
  solar client sync exclude add <planet>
  solar client sync exclude remove <planet>

sync exclude mutates .solar/settings.json (sync_exclude_planets) only;
it does not publish skills. Run solar client sync afterwards to apply.
EOF
}

# Intercept exclude BEFORE the catch-all that forwards args to sync-clients.sh.
if [[ "${1:-}" == "exclude" ]]; then
  shift
  solar_resolve_paths --quiet
  if ! _exclude_raw="$(solar_client_read_sync_exclude_planets "$SOLAR_WORKSPACE")"; then
    echo "ERROR: cannot read sync exclusions; repair workspace settings before continuing" >&2
    exit 1
  fi
  case "${1:-}" in
    list)
      _any=false
      while IFS= read -r _p; do
        [[ -n "$_p" ]] || continue
        printf '%s\n' "$_p"
        _any=true
      done <<<"$_exclude_raw"
      if [[ "$_any" != true ]]; then
        echo "(none)"
      fi
      exit 0
      ;;
    add)
      shift
      planet="${1:-}"
      if [[ -z "$planet" || "$planet" == -* ]]; then
        echo "ERROR: sync exclude add requires <planet>" >&2
        usage_sync >&2
        exit 2
      fi
      _excl=()
      while IFS= read -r _p; do
        [[ -n "$_p" ]] || continue
        if [[ "$_p" == "$planet" ]]; then
          echo "OK: already excluded: $planet"
          exit 0
        fi
        _excl+=("$_p")
      done <<<"$_exclude_raw"
      _excl+=("$planet")
      solar_client_write_sync_exclude_planets "$SOLAR_WORKSPACE" "${_excl[@]}"
      echo "OK: excluded planet from sync: $planet"
      exit 0
      ;;
    remove)
      shift
      planet="${1:-}"
      if [[ -z "$planet" || "$planet" == -* ]]; then
        echo "ERROR: sync exclude remove requires <planet>" >&2
        usage_sync >&2
        exit 2
      fi
      _new=()
      found=false
      while IFS= read -r _p; do
        [[ -n "$_p" ]] || continue
        if [[ "$_p" == "$planet" ]]; then
          found=true
          continue
        fi
        _new+=("$_p")
      done <<<"$_exclude_raw"
      if [[ "$found" != true ]]; then
        echo "OK: planet was not excluded: $planet"
        exit 0
      fi
      if [[ ${#_new[@]} -gt 0 ]]; then
        solar_client_write_sync_exclude_planets "$SOLAR_WORKSPACE" "${_new[@]}"
      else
        solar_client_write_sync_exclude_planets "$SOLAR_WORKSPACE"
      fi
      echo "OK: removed planet from sync exclude: $planet"
      exit 0
      ;;
    -h|--help|"")
      usage_sync
      exit 0
      ;;
    *)
      echo "ERROR: unknown sync exclude subcommand: ${1:-}" >&2
      usage_sync >&2
      exit 2
      ;;
  esac
fi

PORTABLE=false
SYNC_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --portable) PORTABLE=true; shift ;;
    -h|--help)
      usage_sync
      exit 0
      ;;
    *) SYNC_ARGS+=("$1"); shift ;;
  esac
done

solar_resolve_paths --quiet

if [[ "$PORTABLE" == true ]]; then
  bash "$SCRIPT_DIR/client_bundle.sh" create
fi

if [[ ${#SYNC_ARGS[@]} -gt 0 ]]; then
  bash "$(solar_core_dir)/skills/solar-client/scripts/sync-clients.sh" "${SYNC_ARGS[@]}"
else
  bash "$(solar_core_dir)/skills/solar-client/scripts/sync-clients.sh"
fi

_settings="$(solar_client_settings_path "$SOLAR_WORKSPACE")"
if [[ "$(solar_client_manifest_core_source "$_settings")" == "workspace-snapshot" ]]; then
  solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
else
  solar_client_bump_manifest_from_install "$SOLAR_WORKSPACE" "$SOLAR_ROOT"
  solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
fi
