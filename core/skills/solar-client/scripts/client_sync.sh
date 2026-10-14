#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

usage_sync() {
  cat <<'EOF'
Usage:
  solar client sync [--portable] [sync-clients options]
  solar client sync profile show
  solar client sync profile set native|discovery [--essential ID] [--codex-only] [--dry-run]
  solar client sync exclude list
  solar client sync exclude add <planet>
  solar client sync exclude remove <planet>
  solar client sync exclude list|add|remove --client codex [<planet>|<planet>:<agent>]
  solar client sync codex-agents status [--json]
  solar client sync codex-agents enable|disable
  solar client sync codex-agents preview [--contents] [--json]
  solar client sync dashboards status|list [--json]
  solar client sync dashboards seed <planet> [--force]
  solar client sync dashboards register <planet>:<name> [--start-command CMD]
  solar client sync dashboards unregister <planet>:<name>
  solar client sync dashboards enable|disable
  solar client sync exclude-skill list
  solar client sync exclude-skill add <skill>
  solar client sync exclude-skill remove <skill>

sync exclude mutates .solar/settings.json (sync_exclude_planets) only;
exclude-skill mutates sync_exclude_skills. Neither publishes skills: run
solar client sync afterwards to apply.

A skill name is the catalog name: "solar-telegram" for a core skill,
"planet:skill" for a planet one. Per-skill exclusion is the only one that
reaches core; excluding the planet "solar" does not remove a core skill.
A skill that declares "sync: false" in its own SKILL.md is excluded without
any entry here.

Native Codex agents (.codex/agents) are opt-in and off by default.
codex-agents enable turns them on; sync then publishes them with the Codex
client. "exclude --client codex" keeps a planet or a single agent
(<planet>:<agent>) out of Codex agents only; other clients are unchanged.
Global "exclude" (no --client) also applies to Codex agents, in addition to
hiding the planet from every other client. Details:
core/skills/solar-client/references/codex-agents.md

Dashboards are declared by each planet in its own .solar/dashboards.json
(what a surface is and where it answers) and registered per machine here
(which surfaces are active and how to start them). "dashboards register"
writes .solar/settings.json only: it never starts a tool, never probes a port
and never reads or edits a planet file. "dashboards seed <planet>" creates or
validates that planet's declaration and is the only subcommand that writes
inside a planet. The console joins both, is read only, and shows the start
command as copyable text. Details:
core/skills/solar-client/references/dashboards.md
EOF
}

if [[ "${1:-}" == "profile" ]]; then
  shift
  solar_resolve_paths --quiet
  exec python3 "$SCRIPT_DIR/client_profile.py" --workspace "$SOLAR_WORKSPACE" \
    --core "$(solar_core_dir)" "$@"
fi

# Native Codex agents: opt-in publication settings and dry runs.
if [[ "${1:-}" == "codex-agents" ]]; then
  shift
  solar_resolve_paths --quiet
  case "${1:-}" in
    status|enable|disable|preview)
      _ca_cmd="$1"
      shift
      _ca_py="$(solar_client_codex_agents_py)" || exit 1
      exec python3 "$_ca_py" --workspace "$SOLAR_WORKSPACE" "$_ca_cmd" "$@"
      ;;
    -h|--help|"")
      usage_sync
      exit 0
      ;;
    *)
      echo "ERROR: unknown sync codex-agents subcommand: ${1:-}" >&2
      usage_sync >&2
      exit 2
      ;;
  esac
fi

# Dashboard registration: settings only, never a tool start or a port probe.
if [[ "${1:-}" == "dashboards" ]]; then
  shift
  solar_resolve_paths --quiet
  case "${1:-}" in
    status|list|register|unregister|seed|enable|disable)
      _db_cmd="$1"
      shift
      _db_py="$(solar_client_dashboards_py)" || exit 1
      exec python3 "$_db_py" --workspace "$SOLAR_WORKSPACE" "$_db_cmd" "$@"
      ;;
    -h|--help|"")
      usage_sync
      exit 0
      ;;
    *)
      echo "ERROR: unknown sync dashboards subcommand: ${1:-}" >&2
      usage_sync >&2
      exit 2
      ;;
  esac
fi

# Intercept exclude BEFORE the catch-all that forwards args to sync-clients.sh.
if [[ "${1:-}" == "exclude" ]]; then
  shift
  # Optional --client <name> (before or after the planet). Without it, the
  # behaviour below is the original global exclusion.
  _client=""
  _rest=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --client)
        if [[ $# -lt 2 ]]; then
          echo "ERROR: --client requires a value (codex)" >&2
          exit 2
        fi
        _client="$2"
        shift 2
        ;;
      --client=*)
        _client="${1#--client=}"
        shift
        ;;
      *)
        _rest+=("$1")
        shift
        ;;
    esac
  done
  set -- "${_rest[@]+"${_rest[@]}"}"
  if [[ -n "$_client" ]]; then
    if [[ "$_client" != "codex" ]]; then
      echo "ERROR: unknown client for sync exclude: $_client (supported: codex)" >&2
      exit 2
    fi
    solar_resolve_paths --quiet
    _ca_py="$(solar_client_codex_agents_py)" || exit 1
    exec python3 "$_ca_py" --workspace "$SOLAR_WORKSPACE" exclude "$@"
  fi
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

# Per-skill exclusion. Same shape as `exclude`, different list: this one reaches
# core skills, which no planet name can name.
if [[ "${1:-}" == "exclude-skill" ]]; then
  shift
  solar_resolve_paths --quiet
  if ! _skill_raw="$(solar_client_read_sync_exclude_skills "$SOLAR_WORKSPACE")"; then
    echo "ERROR: cannot read per-skill sync exclusions; repair workspace settings before continuing" >&2
    exit 1
  fi
  case "${1:-}" in
    list)
      _any=false
      while IFS= read -r _s; do
        [[ -n "$_s" ]] || continue
        printf '%s\n' "$_s"
        _any=true
      done <<<"$_skill_raw"
      if [[ "$_any" != true ]]; then
        echo "(none)"
      fi
      exit 0
      ;;
    add)
      shift
      skill="${1:-}"
      if [[ -z "$skill" || "$skill" == -* ]]; then
        echo "ERROR: sync exclude-skill add requires <skill>" >&2
        usage_sync >&2
        exit 2
      fi
      _excl=()
      while IFS= read -r _s; do
        [[ -n "$_s" ]] || continue
        if [[ "$_s" == "$skill" ]]; then
          echo "OK: already excluded: $skill"
          exit 0
        fi
        _excl+=("$_s")
      done <<<"$_skill_raw"
      _excl+=("$skill")
      solar_client_write_sync_exclude_skills "$SOLAR_WORKSPACE" "${_excl[@]}"
      echo "OK: excluded skill from sync: $skill"
      exit 0
      ;;
    remove)
      shift
      skill="${1:-}"
      if [[ -z "$skill" || "$skill" == -* ]]; then
        echo "ERROR: sync exclude-skill remove requires <skill>" >&2
        usage_sync >&2
        exit 2
      fi
      _new=()
      found=false
      while IFS= read -r _s; do
        [[ -n "$_s" ]] || continue
        if [[ "$_s" == "$skill" ]]; then
          found=true
          continue
        fi
        _new+=("$_s")
      done <<<"$_skill_raw"
      if [[ "$found" != true ]]; then
        echo "OK: skill was not excluded: $skill"
        exit 0
      fi
      if [[ ${#_new[@]} -gt 0 ]]; then
        solar_client_write_sync_exclude_skills "$SOLAR_WORKSPACE" "${_new[@]}"
      else
        solar_client_write_sync_exclude_skills "$SOLAR_WORKSPACE"
      fi
      echo "OK: removed skill from sync exclude: $skill"
      exit 0
      ;;
    -h|--help|"")
      usage_sync
      exit 0
      ;;
    *)
      echo "ERROR: unknown sync exclude-skill subcommand: ${1:-}" >&2
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

# In portable mode the bundle is only the IDE snapshot. Claim and the state
# cutover use the global install, the same tree the console and the gateway
# were started from. Publishing the IDE links stays on solar_core_dir (the bundle).
_settings="$(solar_client_settings_path "$SOLAR_WORKSPACE")"
SYNC_INSTALL_ROOT="$SOLAR_ROOT"
if [[ -f "$_settings" && "$(solar_client_manifest_core_source "$_settings")" == "workspace-snapshot" ]]; then
  if ! SYNC_INSTALL_ROOT="$(solar_client_portable_update_root)"; then
    echo "ERROR: portable mode claims and migrates the global install, and none was found. Nothing was written and no service was stopped." >&2
    exit 1
  fi
fi

if ! solar_client_claim_workspace "$SOLAR_WORKSPACE" false "$SYNC_INSTALL_ROOT" >/dev/null; then
  echo "ERROR: this runtime refused workspace $SOLAR_WORKSPACE. Nothing was written and no service was stopped." >&2
  exit 1
fi

if [[ "$PORTABLE" == true ]]; then
  bash "$SCRIPT_DIR/client_bundle.sh" create
  # create is a child. This shell still has the pre-create SOLAR_ROOT and
  # SOLAR_CORE_SOURCE, so solar_core_dir would keep publishing from the global
  # install after settings already say workspace-snapshot. Re-resolve so the
  # publish below runs the bundle's sync-clients.sh. Claim and the cutover
  # stay on SYNC_INSTALL_ROOT, captured before this transition.
  solar_resolve_paths --quiet
fi

if [[ ${#SYNC_ARGS[@]} -gt 0 ]]; then
  if ! bash "$(solar_core_dir)/skills/solar-client/scripts/sync-clients.sh" "${SYNC_ARGS[@]}"; then
    echo "ERROR: Client publication failed; sync did not complete." >&2
    exit 1
  fi
else
  if ! bash "$(solar_core_dir)/skills/solar-client/scripts/sync-clients.sh"; then
    echo "ERROR: Client publication failed; sync did not complete." >&2
    exit 1
  fi
fi

_settings="$(solar_client_settings_path "$SOLAR_WORKSPACE")"
if [[ "$(solar_client_manifest_core_source "$_settings")" == "workspace-snapshot" ]]; then
  solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
else
  solar_client_bump_manifest_from_install "$SOLAR_WORKSPACE" "$SOLAR_ROOT"
  solar_client_touch_manifest_synced "$SOLAR_WORKSPACE"
fi

if ! solar_client_state_cutover "$SYNC_INSTALL_ROOT" auto; then
  echo "ERROR: state migration failed after sync. Stopped services were not started." >&2
  exit 1
fi
