#!/usr/bin/env bash
# client_update.sh — global Solar Client update (Fase 2): SOLAR_ROOT git repo or --bundle core/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

CHECK_ONLY=false
REPAIR_ONLY=false
USE_BUNDLE=false
FROM_DEV=true
AUTO_YES=false
FORCE_WORKSPACE=""
TARGET_TAG=""
CHANNEL=""

usage() {
  cat <<'EOF'
Usage:
  solar client update [options]

Updates the global Solar Client install (SOLAR_ROOT). Does not modify SOLAR_WORKSPACE
(sun/, planets/, .env) except with --repair (manifest only).

Options:
  --check              Report installed vs remote/manifest; no changes
  --repair             Repair workspace .solar/manifest.json (OneDrive conflicts)
  --workspace <path>   Workspace for manifest checks/repair (default: discover cwd)
  --tag <ref>          Git checkout <ref> in SOLAR_ROOT (tag or branch)
  --version <vX.Y.Z>   Alias for --tag
  --bundle             Force core/ bundle rsync (skip git even if .git exists)
  --from-dev           Bundle from current SOLAR_ROOT checkout (default with --bundle)
  --from-tag <tag>     Bundle from git tag (with --bundle)
  --channel <name>     Reserved (stable only; beta not implemented)
  --yes, -y            Proceed if SOLAR_ROOT git working tree is dirty
  -h, --help           Show help

After update:
  solar client upgrade   (if IDE artifacts under install)
  solar client sync      (in each active workspace)
  solar client doctor
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true; shift ;;
    --repair) REPAIR_ONLY=true; shift ;;
    --bundle) USE_BUNDLE=true; shift ;;
    --from-dev) FROM_DEV=true; shift ;;
    --from-tag)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: --from-tag requires a value" >&2; exit 2; }
      FROM_DEV=false
      TARGET_TAG="$1"
      USE_BUNDLE=true
      shift
      ;;
    --tag|--version)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: $1 requires a value" >&2; exit 2; }
      TARGET_TAG="$1"
      shift
      ;;
    --channel)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: --channel requires a value" >&2; exit 2; }
      CHANNEL="$1"
      shift
      ;;
    --yes|-y) AUTO_YES=true; shift ;;
    --workspace|--home)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: --workspace requires a path" >&2; exit 2; }
      FORCE_WORKSPACE="$1"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$CHANNEL" && "$CHANNEL" != "stable" ]]; then
  echo "WARN: channel=$CHANNEL not implemented (using stable)" >&2
fi

_resolve_args=()
[[ -n "$FORCE_WORKSPACE" ]] && _resolve_args+=(--workspace "$FORCE_WORKSPACE")
_resolve_args+=(--quiet)
solar_resolve_paths "${_resolve_args[@]}"

INSTALL_ROOT="$SOLAR_ROOT"
BUNDLE_SCRIPT="$(solar_core_dir)/scripts/package_solar_bundle.sh"

if [[ "$REPAIR_ONLY" == true ]]; then
  manifest="$SOLAR_WORKSPACE/.solar/manifest.json"
  if [[ ! -f "$manifest" ]] && [[ ! -d "$SOLAR_WORKSPACE/.solar" ]]; then
    echo "ERROR: no .solar/manifest.json in SOLAR_WORKSPACE=$SOLAR_WORKSPACE" >&2
    exit 1
  fi
  if [[ -f "$manifest" ]] && ! solar_client_manifest_needs_repair "$manifest"; then
    echo "OK: manifest looks valid (layout solar-client-v1.1, core_version present)"
    exit 0
  fi
  solar_client_repair_manifest "$SOLAR_WORKSPACE" "$INSTALL_ROOT"
  echo "OK: repaired .solar/manifest.json from global client ($INSTALL_ROOT)"
  echo "Next: solar client sync && solar client doctor"
  exit 0
fi

if [[ "$CHECK_ONLY" == true ]]; then
  solar_client_update_check_report "$INSTALL_ROOT" "$SOLAR_WORKSPACE"
  exit 0
fi

read -r cur_ver cur_commit < <(solar_client_git_identity "$INSTALL_ROOT")
use_git=false
if [[ "$USE_BUNDLE" != true ]] && [[ -d "$INSTALL_ROOT/.git" ]]; then
  use_git=true
fi

echo "Solar Client update"
echo "  SOLAR_ROOT=$INSTALL_ROOT"
echo "  SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
echo "  mode=$([[ "$use_git" == true ]] && echo git-repo || echo bundle-core)"
echo "  current=$cur_ver (${cur_commit:0:12})"
[[ -n "$TARGET_TAG" ]] && echo "  target=$TARGET_TAG"
echo ""

if [[ "$use_git" == true ]]; then
  backup_path="$(solar_client_backup_install_git "$INSTALL_ROOT" "$cur_ver")"
  echo "OK: backup at $backup_path"
  solar_client_apply_git_update "$INSTALL_ROOT" "$TARGET_TAG" "$AUTO_YES"
else
  if [[ ! -f "$BUNDLE_SCRIPT" ]]; then
    echo "ERROR: bundle script not found: $BUNDLE_SCRIPT" >&2
    exit 1
  fi
  backup_path="$(solar_client_backup_install_core "$INSTALL_ROOT" "$cur_ver")"
  echo "OK: backup core/ at $backup_path"
  tag_arg=""
  [[ -n "$TARGET_TAG" ]] && tag_arg="$TARGET_TAG"
  if [[ "$FROM_DEV" == true && -z "$tag_arg" ]]; then
    solar_client_apply_bundle_update "$INSTALL_ROOT" true "" "$BUNDLE_SCRIPT"
  else
    solar_client_apply_bundle_update "$INSTALL_ROOT" false "$tag_arg" "$BUNDLE_SCRIPT"
  fi
fi

solar_client_rotate_backups "$INSTALL_ROOT" 5

read -r new_ver new_commit < <(solar_client_git_identity "$INSTALL_ROOT")
echo ""
echo "OK: update complete — $new_ver (${new_commit:0:12})"

if ! solar_client_paths_equal "$INSTALL_ROOT" "$SOLAR_WORKSPACE"; then
  echo "HINT: run solar client upgrade in SOLAR_WORKSPACE if install has IDE artifacts"
fi
echo "Next steps (per workspace):"
echo "  cd \"$SOLAR_WORKSPACE\""
echo "  solar client sync"
echo "  solar client doctor"
