#!/usr/bin/env bash
# client_update_staged.sh — the update sequence, run from the TARGET version in staging.
#
# `solar client update` prepares the target beside the live install and hands over to this
# script, which then owns the order that keeps the runtime safe:
#
#   maintenance barrier -> ticks paused -> async work drained -> other services stopped ->
#   cutover under the exclusive state lock (backup, then the code is replaced, then the schema
#   is migrated and validated) -> services started -> code and schema verified -> ticks
#   resumed -> barrier released.
#
# An updater that already replaced the code before stopping anything (every release up to
# v0.47.1) cannot give that order. For that first installation, prepare the target yourself
# and run this script from it with explicit paths:
#
#   git clone --branch <tag> <repo-url> /tmp/solar-staging
#   bash /tmp/solar-staging/core/skills/solar-client/scripts/client_update_staged.sh \
#     --install-root ~/.local/share/solar --workspace <workspace> --runtime-root <runtime> \
#     --stage-root /tmp/solar-staging --mode git --target <tag>
#
# Usage:
#   client_update_staged.sh --install-root P --workspace W --runtime-root R --stage-root S \
#     --mode git|bundle [--target REF] [--apply-hook H] [--target-identity "V COMMIT"] \
#     [--restart-mode auto|never|always] [--reinstall-launchagent] [--portable] \
#     [--did-backup] [--verbose] [--no-sync]
#   client_update_staged.sh --resume --install-root P --workspace W --runtime-root R
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

INSTALL_ROOT=""
WORKSPACE=""
RUNTIME_ROOT=""
STAGE_ROOT=""
MODE=git
TARGET=""
APPLY_HOOK=""
TARGET_IDENTITY=""
RESTART_MODE=auto
REINSTALL_LAUNCHAGENT=false
PORTABLE=false
DID_BACKUP=false
RESUME=false
VERBOSE=false
RUN_SYNC=true
ORIG_ARGS=("$@")

need() { [[ $# -ge 2 ]] || { echo "ERROR: $1 requires a value" >&2; exit 2; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-root) need "$@"; INSTALL_ROOT="$2"; shift 2 ;;
    --workspace) need "$@"; WORKSPACE="$2"; shift 2 ;;
    --runtime-root) need "$@"; RUNTIME_ROOT="$2"; shift 2 ;;
    --stage-root) need "$@"; STAGE_ROOT="$2"; shift 2 ;;
    --mode) need "$@"; MODE="$2"; shift 2 ;;
    --target) need "$@"; TARGET="$2"; shift 2 ;;
    --apply-hook) need "$@"; APPLY_HOOK="$2"; shift 2 ;;
    --target-identity) need "$@"; TARGET_IDENTITY="$2"; shift 2 ;;
    --restart-mode) need "$@"; RESTART_MODE="$2"; shift 2 ;;
    --reinstall-launchagent) REINSTALL_LAUNCHAGENT=true; shift ;;
    --portable) PORTABLE=true; shift ;;
    --did-backup) DID_BACKUP=true; shift ;;
    --resume) RESUME=true; shift ;;
    --verbose) VERBOSE=true; shift ;;
    --no-sync) RUN_SYNC=false; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//; /^set -euo/d'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

for name in INSTALL_ROOT WORKSPACE RUNTIME_ROOT; do
  if [[ -z "${!name}" ]]; then
    flag="$(printf '%s' "${name//_/-}" | tr '[:upper:]' '[:lower:]')"
    echo "ERROR: --$flag is required (explicit paths: this script never guesses the install or the runtime)" >&2
    exit 2
  fi
done
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd -P)"
export SOLAR_ROOT="$INSTALL_ROOT" SOLAR_WORKSPACE="$WORKSPACE" SOLAR_RUNTIME_ROOT="$RUNTIME_ROOT"

# Short view: run this script again with its output through the filter; the full output goes to
# a log. The front updater may already have done it (SOLAR_CLIENT_UPDATE_VIEWED).
if [[ "$VERBOSE" != true && "${SOLAR_CLIENT_VERBOSE:-}" != 1 && "${SOLAR_CLIENT_UPDATE_VIEWED:-}" != 1 ]]; then
  export SOLAR_CLIENT_UPDATE_VIEWED=1
  solar_client_update_log_rotate "$RUNTIME_ROOT"
  bash "${BASH_SOURCE[0]}" "${ORIG_ARGS[@]}" 2>&1 | solar_client_update_view "$(solar_client_update_log_path "$RUNTIME_ROOT")"
  exit "${PIPESTATUS[0]}"
fi

echo "Solar Client update (staged entrypoint)"
echo "  SOLAR_ROOT=$INSTALL_ROOT"
echo "  SOLAR_WORKSPACE=$WORKSPACE"
echo "  runtime=$RUNTIME_ROOT"

if [[ "$RESUME" == true ]]; then
  if ! solar_client_maintenance_held; then
    echo "No update is in progress: nothing to resume."
    exit 0
  fi
  echo ""
  # The recorded phase says what is left. Before the cutover finished, the staged copy named in
  # the barrier supplies the code; the hook is idempotent (the same commit, the same files).
  export SOLAR_CLIENT_UPDATE_STAGING="$(solar_client_maintenance_field staging)"
  export SOLAR_CLIENT_UPDATE_TARGET_IDENTITY="$(solar_client_maintenance_field to)"
  export SOLAR_CLIENT_CUTOVER_DONE=1
  resumed_stage="$SOLAR_CLIENT_UPDATE_STAGING"
  if ! solar_client_state_cutover "$INSTALL_ROOT" "$RESTART_MODE" "" resume; then
    echo "ERROR: the update could not be resumed (see above). The maintenance barrier stays." >&2
    exit 1
  fi
  if ! solar_client_maintenance_held && [[ -n "$resumed_stage" ]]; then
    case "$(basename "$(dirname "$resumed_stage")")" in
      solar-update-staging.*) rm -rf "$(dirname "$resumed_stage")" ;;
    esac
  fi
  exit 0
fi

if [[ -z "$STAGE_ROOT" ]]; then
  STAGE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd -P)"
fi
if [[ -z "$APPLY_HOOK" ]]; then
  # Run by hand from a prepared tree: write the hook from the target given.
  staging="$(mktemp -d "${TMPDIR:-/tmp}/solar-update-staging.XXXXXX")"
  commit=""
  if [[ "$MODE" == git ]]; then
    commit="$(git -C "$STAGE_ROOT" rev-parse HEAD)"
    [[ -n "$TARGET" ]] || TARGET="$commit"
    if ! git -C "$INSTALL_ROOT" rev-parse -q --verify "${commit}^{commit}" >/dev/null 2>&1; then
      git -C "$INSTALL_ROOT" fetch --quiet --no-tags "$STAGE_ROOT" "$commit"
    fi
    if ! solar_client_git_clean "$INSTALL_ROOT"; then
      echo "ERROR: SOLAR_ROOT has uncommitted changes; commit or stash them first. Nothing was changed." >&2
      exit 1
    fi
  fi
  solar_client_validate_staged "$STAGE_ROOT"
  solar_client_write_apply_hook "$staging/apply-hook.sh" "$INSTALL_ROOT" "$MODE" "$TARGET" "$commit" "$STAGE_ROOT"
  APPLY_HOOK="$staging/apply-hook.sh"
fi
if [[ -z "$TARGET_IDENTITY" && "$MODE" == git ]]; then
  git_identity="$(solar_client_git_identity "$STAGE_ROOT")"
  read -r _tv _tc <<< "$git_identity"
  TARGET_IDENTITY="$_tv $_tc"
fi

export SOLAR_CLIENT_UPDATE_STAGING="$STAGE_ROOT"
export SOLAR_CLIENT_UPDATE_TARGET_IDENTITY="$TARGET_IDENTITY"
# solar_client_state_cutover is the update; the restart helper below must not run it again.
export SOLAR_CLIENT_CUTOVER_DONE=1

restart_failed=0
if ! solar_client_state_cutover "$INSTALL_ROOT" "$RESTART_MODE" "$APPLY_HOOK"; then
  echo "" >&2
  echo "ERROR: the update did not complete. The services and ticks that were stopped stay stopped," >&2
  echo "       the maintenance barrier stays held, and the backups and the event log are kept:" >&2
  echo "         events:  $(solar_client_update_events_file)" >&2
  echo "         backups: $RUNTIME_ROOT/state-backups/" >&2
  echo "       Fix the cause, then run: solar client update --resume" >&2
  exit 1
fi

git_identity="$(solar_client_git_identity "$INSTALL_ROOT")"
read -r new_ver new_commit <<< "$git_identity"
echo ""
echo "OK: update complete — $new_ver (${new_commit:0:12})"
if [[ "$DID_BACKUP" == true ]]; then
  solar_client_rotate_backups "$INSTALL_ROOT" 5 "$WORKSPACE"
fi
if solar_client_upgrade_needed "$INSTALL_ROOT" "$WORKSPACE"; then
  echo "  ! solar client upgrade is needed in this workspace (IDE artifacts or an older layout)"
fi

echo ""
SOLAR_CLIENT_GATEWAY_RESTARTED=false
if solar_client_maintenance_held; then
  # --no-restart: nothing may start before the explicit resume, so nothing is reinstalled.
  solar_client_report_launchagent_binding "$INSTALL_ROOT" false || true
else
  solar_client_report_launchagent_binding "$INSTALL_ROOT" "$REINSTALL_LAUNCHAGENT" || restart_failed=1
fi

if [[ "$PORTABLE" == true ]]; then
  echo "Regenerating the workspace bundle from the global install"
  bundle_script="$INSTALL_ROOT/core/skills/solar-client/scripts/client_bundle.sh"
  if [[ ! -f "$bundle_script" ]]; then
    echo "ERROR: bundle script missing in the global install ($INSTALL_ROOT)." >&2
    restart_failed=1
  elif ! (
    cd "$WORKSPACE"
    SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$INSTALL_ROOT" SOLAR_ROOT="$INSTALL_ROOT" \
      bash "$bundle_script" create
  ); then
    echo "ERROR: the global install was updated, but the workspace bundle was not regenerated. Run: solar client bundle create" >&2
    restart_failed=1
  fi
fi

# The follow-up the person would run by hand: publish skills to the IDEs and check the workspace.
# A failure here is reported, never an update failure: the update itself is already verified.
if solar_client_maintenance_held; then
  echo "Next: solar client update --resume, then solar client sync"
elif [[ "$RUN_SYNC" == true && -f "$(solar_client_settings_path "$WORKSPACE")" ]]; then
  if (cd "$WORKSPACE" && SOLAR_ROOT="$INSTALL_ROOT" bash "$SCRIPT_DIR/solar" client sync); then
    echo "  ✓ skills, agents and commands published to the IDEs"
  else
    echo "  ! solar client sync failed: run it in $WORKSPACE"
  fi
  doctor_out="$(cd "$WORKSPACE" && SOLAR_ROOT="$INSTALL_ROOT" bash "$SCRIPT_DIR/solar" client doctor 2>&1)" || true
  printf '%s\n' "$doctor_out"
  doctor_summary="$(printf '%s\n' "$doctor_out" | grep '^Summary:' | tail -1 || true)"
  if [[ -n "$doctor_summary" && "$doctor_summary" == *" 0 error(s)"* ]]; then
    echo "  ✓ doctor: ${doctor_summary#Summary: }"
  else
    echo "  ! doctor: ${doctor_summary#Summary: } — run: solar client doctor"
  fi
else
  echo "Next: solar client sync"
fi

if solar_client_maintenance_held; then
  echo ""
  echo "Services and ticks are stopped and the maintenance barrier is held (--no-restart)."
  echo "Start them, verify and release with: solar client update --resume"
else
  # Done and released: the staging copy this updater made is no longer needed. A tree the
  # person prepared by hand (--stage-root) is theirs and stays.
  case "$(basename "$(dirname "$APPLY_HOOK")")" in
    solar-update-staging.*) rm -rf "$(dirname "$APPLY_HOOK")" ;;
  esac
fi
if [[ "$restart_failed" -ne 0 ]]; then
  echo "" >&2
  echo "ERROR: update applied, but a follow-up step failed (see above)." >&2
  exit 1
fi
