#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

PORTABLE=false
SYNC_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --portable) PORTABLE=true; shift ;;
    -h|--help)
      echo "Usage: solar client sync [--portable] [sync-clients options]"
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
  bash "$(solar_core_dir)/scripts/sync-clients.sh" "${SYNC_ARGS[@]}"
else
  bash "$(solar_core_dir)/scripts/sync-clients.sh"
fi

if [[ "$(solar_client_manifest_core_source "$SOLAR_WORKSPACE/.solar/manifest.json")" == "workspace-snapshot" ]]; then
  solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
else
  solar_client_bump_manifest_from_install "$SOLAR_WORKSPACE" "$SOLAR_ROOT"
  solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
fi
