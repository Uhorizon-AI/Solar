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
REINSTALL_LAUNCHAGENT=false
RESTART_SERVICES=auto
RESUME=false
VERBOSE=false
NO_SYNC=false
ORIG_ARGS=("$@")

usage() {
  cat <<'EOF'
Usage:
  solar client update [options]

Updates the global Solar Client install (SOLAR_ROOT). Does not modify SOLAR_WORKSPACE
sun/ or planets/. In portable mode (core_source workspace-snapshot) the bundle
under .solar/bundle is the snapshot IDEs read; this command updates the global
install and then regenerates that bundle. The LaunchAgent keeps running from
the global install, so its plist SOLAR_ROOT stays that path. If no global
install exists, update refuses before it changes anything. A global install
without a git checkout is updated with --bundle (bundle-core), the same
contract as a non-portable install. A .git directory is required only when
the update checks out a ref.
New updaters atomically migrate SOLAR_ROUTER_PROVIDER_PRIORITY /
SOLAR_AI_PROVIDER_PRIORITY in the workspace .env (gemini→agy) before apply.
The first router run after a legacy updater performs the same one-time migration.
--repair only touches .solar/settings.json (migrates legacy manifest.json).

The target version is first prepared and checked in a staging copy; the live install is
not touched until the update runs. The sequence then runs from the staged copy
(client_update_staged.sh): a maintenance barrier refuses every claim and launcher, the
ticks are paused, the async work drains (a timeout of 120 seconds aborts the update before
anything is replaced), the other services stop, and under the exclusive state lock the
runtime is backed up, the code is replaced and the schema is migrated and validated. Only
then are the services that were running started again, the code and schema verified, the
ticks resumed and the barrier released. A failure keeps the barrier and the services
stopped; --resume continues the same operation, never a new one.
--check does not migrate, stop or write anything. --no-restart does everything up to the
migration and leaves services and ticks stopped, with the barrier held, until --resume.

On macOS, after a successful update, reports LaunchAgent SOLAR_ROOT binding (read-only
status). Use --reinstall-launchagent on a real update (not with --check) to rewrite
the plist and restart the transport gateway.

Options:
  --check              Report installed vs remote/settings/LaunchAgent; no changes.
                       Read-only: never restarts services, so --restart and
                       --no-restart do not apply to it
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
  --reinstall-launchagent
                       After update completes, reinstall macOS LaunchAgent when
                       SOLAR_ROOT binding is stale and restart transport gateway.
                       Incompatible with --check (read-only).
  --no-restart         Do not restart running services after the update; ticks and
                       dispatch stay suspended until --resume
  --resume             Continue an update that was interrupted, failed or was left
                       held by --no-restart: same operation, recorded phase
  --restart            Restart running services even if the version did not change
  --no-sync            Do not run solar client sync and doctor after the update
  --verbose            Print everything the update does (by default a short summary is
                       printed and the full output goes to <runtime>/update-logs/)
  --yes, -y            Proceed if SOLAR_ROOT git working tree is dirty
  -h, --help           Show help

After the update, sync and doctor run in this workspace; the update says when
`solar client upgrade` is needed. In other workspaces run: solar client sync
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
    --reinstall-launchagent) REINSTALL_LAUNCHAGENT=true; shift ;;
    --no-restart) RESTART_SERVICES=never; shift ;;
    --resume) RESUME=true; shift ;;
    --verbose) VERBOSE=true; shift ;;
    --no-sync) NO_SYNC=true; shift ;;
    --restart) RESTART_SERVICES=always; shift ;;
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

if [[ "$RESUME" == true && ( "$CHECK_ONLY" == true || "$REPAIR_ONLY" == true || "$REINSTALL_LAUNCHAGENT" == true ) ]]; then
  echo "ERROR: --resume continues an interrupted update; do not combine it with --check, --repair or --reinstall-launchagent" >&2
  exit 2
fi

if [[ "$CHECK_ONLY" == true && "$REINSTALL_LAUNCHAGENT" == true ]]; then
  echo "ERROR: --check is read-only; do not combine with --reinstall-launchagent" >&2
  echo "  Report only:  solar client update --check" >&2
  echo "  Repair host:  solar client update --reinstall-launchagent" >&2
  exit 2
fi

if [[ -n "$CHANNEL" && "$CHANNEL" != "stable" ]]; then
  echo "WARN: channel=$CHANNEL not implemented (using stable)" >&2
fi

_resolve_args=()
[[ -n "$FORCE_WORKSPACE" ]] && _resolve_args+=(--workspace "$FORCE_WORKSPACE")
_resolve_args+=(--quiet)
solar_resolve_paths "${_resolve_args[@]}"

PORTABLE_UPDATE=false
_settings_now="$(solar_client_settings_path "$SOLAR_WORKSPACE")"
if [[ -f "$_settings_now" ]] && [[ "$(solar_client_manifest_core_source "$_settings_now")" == "workspace-snapshot" ]]; then
  if ! INSTALL_ROOT="$(solar_client_portable_update_root)"; then
    echo "ERROR: portable mode updates the global install, and none was found. Nothing was changed." >&2
    exit 1
  fi
  # .git is required only by the git checkout below. Without it, --bundle
  # (and an install that has no .git) updates this global via bundle-core.
  # The snapshot is not the install either way.
  PORTABLE_UPDATE=true
else
  INSTALL_ROOT="$SOLAR_ROOT"
fi

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
  solar_client_maintenance_report
  # --check is always read-only (combination with --reinstall-launchagent rejected above).
  solar_client_report_launchagent_binding "$INSTALL_ROOT" false
  exit 0
fi

# Short view: the same command again with its output through the filter (full output in a log).
if [[ "$VERBOSE" != true && "${SOLAR_CLIENT_VERBOSE:-}" != 1 && "${SOLAR_CLIENT_UPDATE_VIEWED:-}" != 1 ]]; then
  export SOLAR_CLIENT_UPDATE_VIEWED=1
  _view_runtime="$(solar_runtime_root)"
  bash "${BASH_SOURCE[0]}" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"} 2>&1 | solar_client_update_view "$(solar_client_update_log_path "$_view_runtime")"
  exit "${PIPESTATUS[0]}"
fi

if ! solar_client_claim_workspace "$SOLAR_WORKSPACE" false "$INSTALL_ROOT" >/dev/null; then
  echo "ERROR: this runtime refused workspace $SOLAR_WORKSPACE. Install, settings and services were left unchanged." >&2
  exit 1
fi

if [[ "$RESUME" == true ]]; then
  if ! solar_client_maintenance_held; then
    echo "No update is in progress: nothing to resume."
    exit 0
  fi
  solar_client_maintenance_report
  # Before the code was replaced the staged copy has the target; afterwards the install has it.
  _resume_stage="$(solar_client_maintenance_field staging)"
  _resume_entry="$_resume_stage/core/skills/solar-client/scripts/client_update_staged.sh"
  case "$(solar_client_maintenance_field phase)" in
    cutover-done|held-no-restart|restarting|restart-failed) _resume_entry="$INSTALL_ROOT/core/skills/solar-client/scripts/client_update_staged.sh" ;;
  esac
  if [[ ! -f "$_resume_entry" ]]; then
    echo "ERROR: the entrypoint to resume with is gone ($_resume_entry). Nothing was changed; the barrier stays." >&2
    exit 1
  fi
  _resume_args=()
  # Only what the entrypoint to resume with understands: it may predate these options.
  [[ "$VERBOSE" == true ]] && solar_client_staged_supports "$_resume_entry" "--verbose" && _resume_args+=(--verbose)
  [[ "$NO_SYNC" == true ]] && solar_client_staged_supports "$_resume_entry" "--no-sync" && _resume_args+=(--no-sync)
  exec bash "$_resume_entry" --resume --install-root "$INSTALL_ROOT" --workspace "$SOLAR_WORKSPACE" \
    --runtime-root "$(solar_runtime_root)" --restart-mode "$RESTART_SERVICES" ${_resume_args[@]+"${_resume_args[@]}"}
fi

if solar_client_maintenance_held; then
  solar_client_maintenance_report >&2
  echo "ERROR: another update is in progress or was interrupted. Resume it with: solar client update --resume" >&2
  echo "       Nothing was changed." >&2
  exit 1
fi

# Wait for the identity subprocess before writing to the caller's pipe. On macOS
# Bash 3.2 an outstanding process-substitution SIGCHLD can interrupt echo (EINTR).
identity="$(solar_client_git_identity "$INSTALL_ROOT")"
read -r cur_ver cur_commit <<< "$identity"
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
APPLY_MODE=git
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
    if ! solar_client_git_clean "$INSTALL_ROOT"; then
      echo "SKIP: git install — no rsync snapshot (uncommitted changes; commit/stash or --backup)"
    else
      echo "SKIP: git install — no rsync snapshot (rollback: git -C \"$INSTALL_ROOT\" checkout <tag>)"
    fi
    echo "      use --backup to force an rsync snapshot"
  fi
  BUNDLE_SCRIPT=""
  FROM_DEV_ARG=true
else
  APPLY_MODE=bundle
  BUNDLE_SCRIPT="$INSTALL_ROOT/core/skills/solar-client/scripts/package_solar_bundle.sh"
  if [[ ! -f "$BUNDLE_SCRIPT" ]]; then
    echo "ERROR: bundle script not found: $BUNDLE_SCRIPT" >&2
    exit 1
  fi
  backup_path="$(solar_client_backup_install_core "$INSTALL_ROOT" "$cur_ver" "$SOLAR_WORKSPACE")"
  echo "OK: backup core/ at $backup_path"
  DID_BACKUP=true
  FROM_DEV_ARG="$FROM_DEV"
fi

# Prepare and check the target beside the install. Nothing of the live install changes here.
UPDATE_STAGING="$(mktemp -d "${TMPDIR:-/tmp}/solar-update-staging.XXXXXX")"
echo "Staging the target version in $UPDATE_STAGING"
if ! STAGE_ROOT="$(solar_client_stage_update "$INSTALL_ROOT" "$APPLY_MODE" "$TARGET_TAG" "$UPDATE_STAGING" "$AUTO_YES" "$BUNDLE_SCRIPT" "$FROM_DEV_ARG")"; then
  echo "ERROR: the target version could not be prepared. The install, the runtime and the services were left unchanged." >&2
  rm -rf "$UPDATE_STAGING"
  exit 1
fi
echo "OK: staged and checked: $STAGE_ROOT"
echo ""

STAGED_ARGS=(--install-root "$INSTALL_ROOT" --workspace "$SOLAR_WORKSPACE" --runtime-root "$(solar_runtime_root)"
  --stage-root "$STAGE_ROOT" --mode "$APPLY_MODE" --target "$TARGET_TAG"
  --apply-hook "$UPDATE_STAGING/apply-hook.sh" --restart-mode "$RESTART_SERVICES")
[[ "$DID_BACKUP" == true ]] && STAGED_ARGS+=(--did-backup)
[[ "$REINSTALL_LAUNCHAGENT" == true ]] && STAGED_ARGS+=(--reinstall-launchagent)
[[ "$PORTABLE_UPDATE" == true ]] && STAGED_ARGS+=(--portable)
# The target's entrypoint may predate these options; it would refuse them as unknown.
_staged_entry="$STAGE_ROOT/core/skills/solar-client/scripts/client_update_staged.sh"
[[ "$NO_SYNC" == true ]] && solar_client_staged_supports "$_staged_entry" "--no-sync" && STAGED_ARGS+=(--no-sync)
[[ "$VERBOSE" == true ]] && solar_client_staged_supports "$_staged_entry" "--verbose" && STAGED_ARGS+=(--verbose)

# From here the TARGET version's own entrypoint runs the sequence; this (possibly old) updater
# never replaces code or stops a service itself.
exec bash "$STAGE_ROOT/core/skills/solar-client/scripts/client_update_staged.sh" "${STAGED_ARGS[@]}"
