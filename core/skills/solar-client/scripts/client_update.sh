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
FORCE_BACKUP=false
FORCE_WORKSPACE=""
TARGET_TAG=""
CHANNEL=""

usage() {
  cat <<'EOF'
Usage:
  solar client update [options]

Updates the global Solar Client install (SOLAR_ROOT). Does not modify SOLAR_WORKSPACE
sun/ or planets/. New updaters atomically migrate SOLAR_ROUTER_PROVIDER_PRIORITY /
SOLAR_AI_PROVIDER_PRIORITY in the workspace .env (gemini→agy) before apply.
The first router run after a legacy updater performs the same one-time migration.
--repair only touches .solar/settings.json (migrates legacy manifest.json).

Options:
  --check              Report installed vs remote/settings; no changes
  --repair             Repair workspace .solar/settings.json (OneDrive conflicts)
  --workspace <path>   Workspace for settings checks/repair (default: discover cwd)
  --ref <ref>          Git checkout <ref> in SOLAR_ROOT (tag, branch, or commit)
  --tag <ref>          Alias for --ref
  --version <vX.Y.Z>   Alias for --ref
  --bundle             Force core/ bundle rsync (skip git even if .git exists)
  --from-dev           Bundle from current SOLAR_ROOT checkout (default with --bundle)
  --from-tag <tag>     Bundle from git tag (with --bundle)
  --channel <name>     Reserved (stable only; beta not implemented)
  --backup             Rsync snapshot before update (git mode only; default: no rsync, use git tags)
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
    --ref|--tag|--version)
      opt="$1"
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: $opt requires a value" >&2; exit 2; }
      TARGET_TAG="$1"
      shift
      ;;
    --channel)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: --channel requires a value" >&2; exit 2; }
      CHANNEL="$1"
      shift
      ;;
    --backup) FORCE_BACKUP=true; shift ;;
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
BUNDLE_SCRIPT="$(solar_core_dir)/skills/solar-client/scripts/package_solar_bundle.sh"

if [[ "$REPAIR_ONLY" == true ]]; then
  if ! solar_client_settings_exists "$SOLAR_WORKSPACE" && [[ ! -d "$SOLAR_WORKSPACE/.solar" ]]; then
    echo "ERROR: no .solar/settings.json (or legacy manifest) in SOLAR_WORKSPACE=$SOLAR_WORKSPACE" >&2
    exit 1
  fi
  settings_path="$(solar_client_settings_path "$SOLAR_WORKSPACE")"
  if [[ -f "$settings_path" ]] && ! solar_client_manifest_needs_repair "$settings_path"; then
    echo "OK: settings look valid (layout solar-client-v1.1|v1.2, core_version present)"
    exit 0
  fi
  solar_client_repair_manifest "$SOLAR_WORKSPACE" "$INSTALL_ROOT"
  echo "OK: repaired .solar/settings.json from global client ($INSTALL_ROOT)"
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

# Prefer migrate-before when this (running) tree already ships the migrator.
_MIGRATE_ENV_AGY="$SCRIPT_DIR/migrate_workspace_env_agy.py"
if [[ -f "$SOLAR_WORKSPACE/.env" && -f "$_MIGRATE_ENV_AGY" ]]; then
  echo "Migrating workspace .env provider priority (gemini→agy) if needed…"
  if ! _mig_out="$(python3 "$_MIGRATE_ENV_AGY" "$SOLAR_WORKSPACE/.env" 2>&1)"; then
    echo "ERROR: workspace .env priority migration failed; aborting before framework update" >&2
    echo "$_mig_out" >&2
    exit 1
  fi
  echo "$_mig_out"
fi

DID_BACKUP=false
if [[ "$use_git" == true ]]; then
  if [[ -z "$TARGET_TAG" ]]; then
    TARGET_TAG="$(solar_client_resolve_stable_release_tag)" || {
      echo "ERROR: could not resolve stable release; pass --ref explicitly" >&2
      exit 1
    }
    echo "  target=$TARGET_TAG (stable release)"
  fi
  if solar_client_should_rsync_backup_git "$INSTALL_ROOT" "$FORCE_BACKUP"; then
    backup_path="$(solar_client_backup_install_git "$INSTALL_ROOT" "$cur_ver" "$SOLAR_WORKSPACE")"
    echo "OK: backup at $backup_path"
    DID_BACKUP=true
  else
    if solar_client_git_dirty "$INSTALL_ROOT"; then
      echo "SKIP: git install — no rsync snapshot (uncommitted changes; commit/stash or --backup)"
    else
      echo "SKIP: git install — no rsync snapshot (rollback: git -C \"$INSTALL_ROOT\" checkout <tag>)"
    fi
    echo "      use --backup to force an rsync snapshot"
  fi
  solar_client_apply_git_update "$INSTALL_ROOT" "$TARGET_TAG" "$AUTO_YES"
else
  if [[ ! -f "$BUNDLE_SCRIPT" ]]; then
    echo "ERROR: bundle script not found: $BUNDLE_SCRIPT" >&2
    exit 1
  fi
  backup_path="$(solar_client_backup_install_core "$INSTALL_ROOT" "$cur_ver" "$SOLAR_WORKSPACE")"
  echo "OK: backup core/ at $backup_path"
  DID_BACKUP=true
  tag_arg=""
  [[ -n "$TARGET_TAG" ]] && tag_arg="$TARGET_TAG"
  if [[ "$FROM_DEV" == true && -z "$tag_arg" ]]; then
    solar_client_apply_bundle_update "$INSTALL_ROOT" true "" "$BUNDLE_SCRIPT"
  else
    solar_client_apply_bundle_update "$INSTALL_ROOT" false "$tag_arg" "$BUNDLE_SCRIPT"
  fi
fi

if [[ "$DID_BACKUP" == true ]]; then
  solar_client_rotate_backups "$INSTALL_ROOT" 5 "$SOLAR_WORKSPACE"
fi

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
