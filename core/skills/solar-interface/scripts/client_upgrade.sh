#!/usr/bin/env bash
# client_upgrade.sh — upgrade workspace to solar-client-v1.1 + install hygiene (Fase 1.2).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

CHECK_ONLY=false
REPAIR_GOVERNANCE=false
FORCE_WORKSPACE=""
RESTRUCTURE=false
SKIP_PRUNE_INSTALL=false

usage() {
  cat <<'EOF'
Usage:
  solar client upgrade [--check] [--repair-governance] [--workspace <path>]
                     [--restructure] [--skip-prune-install]

Upgrades to the Solar Client model (solar-client-v1.1):
  - Reports SOLAR_WORKSPACE, SOLAR_ROOT, layout, install git tag
  - Workspace: removes obsolete .solar/core/ and orphan .solar/.env; writes manifest
  - Install hygiene: removes IDE/agent artifacts under SOLAR_ROOT when distinct from workspace
  - Optional --restructure: legacy monorepo (core/ at workspace root) -> solar/ subdirectory

Options:
  --check               Dry-run: print planned actions only
  --repair-governance   Replace AGENTS.md and IDE symlinks from template (backs up first)
  --workspace <path>    Target workspace (default: discover from cwd)
  --restructure         Move core/ (+ .git) under solar/ for legacy_root layout only
  --skip-prune-install  Skip removing IDE dirs under SOLAR_ROOT
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true; shift ;;
    --repair-governance) REPAIR_GOVERNANCE=true; shift ;;
    --restructure) RESTRUCTURE=true; shift ;;
    --skip-prune-install) SKIP_PRUNE_INSTALL=true; shift ;;
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

_resolve_args=()
[[ -n "$FORCE_WORKSPACE" ]] && _resolve_args+=(--workspace "$FORCE_WORKSPACE")
_resolve_args+=(--relaxed --quiet)
solar_resolve_paths "${_resolve_args[@]}"

INSTALL_ROOT="$SOLAR_ROOT"
DRY_RUN=false
[[ "$CHECK_ONLY" == true ]] && DRY_RUN=true

actions=()

solar_client_print_upgrade_report "$SOLAR_WORKSPACE" "$SOLAR_ROOT"
echo ""

if [[ "$RESTRUCTURE" == true ]]; then
  if [[ "$DRY_RUN" == true ]]; then
    if solar_client_restructure_needed "$SOLAR_WORKSPACE"; then
      while IFS= read -r line; do
        [[ -n "$line" ]] && actions+=("restructure: $line")
      done < <(solar_client_restructure_plan "$SOLAR_WORKSPACE")
    else
      actions+=("restructure: skip (not legacy_root or solar/core/ exists)")
    fi
  else
    solar_client_restructure_apply "$SOLAR_WORKSPACE" false
    _resolve_args=()
    [[ -n "$FORCE_WORKSPACE" ]] && _resolve_args+=(--workspace "$FORCE_WORKSPACE")
    _resolve_args+=(--relaxed --quiet)
    solar_resolve_paths "${_resolve_args[@]}"
    INSTALL_ROOT="$SOLAR_ROOT"
    solar_client_print_upgrade_report "$SOLAR_WORKSPACE" "$SOLAR_ROOT"
    echo ""
  fi
fi

[[ -d "$SOLAR_WORKSPACE/.solar/core" ]] && actions+=("remove .solar/core/")
[[ -f "$SOLAR_WORKSPACE/.solar/.env" ]] && actions+=("remove orphan .solar/.env")
actions+=("write .solar/manifest.json (solar-client-v1.1)")
[[ "$REPAIR_GOVERNANCE" == true ]] && actions+=("repair governance (AGENTS.md + IDE symlinks)")

if [[ "$SKIP_PRUNE_INSTALL" != true ]] && ! solar_client_paths_equal "$SOLAR_ROOT" "$SOLAR_WORKSPACE"; then
  while IFS= read -r path; do
    [[ -n "$path" ]] && actions+=("prune install: $path")
  done < <(solar_client_list_install_artifacts "$SOLAR_ROOT")
elif [[ "$SKIP_PRUNE_INSTALL" == true ]]; then
  actions+=("prune install: skipped (--skip-prune-install)")
fi

if [[ "$CHECK_ONLY" == true ]]; then
  echo "solar client upgrade --check"
  for a in "${actions[@]}"; do
    echo "  would: $a"
  done
  exit 0
fi

if [[ -d "$SOLAR_WORKSPACE/.solar/core" ]]; then
  rm -rf "$SOLAR_WORKSPACE/.solar/core"
  echo "OK: removed obsolete .solar/core/"
fi
if [[ -f "$SOLAR_WORKSPACE/.solar/.env" ]]; then
  rm -f "$SOLAR_WORKSPACE/.solar/.env"
  echo "OK: removed orphan .solar/.env"
fi

solar_client_write_manifest_v11 "$SOLAR_WORKSPACE" "$INSTALL_ROOT" preserve_synced=1
echo "OK: updated .solar/manifest.json (layout solar-client-v1.1)"

if [[ "$REPAIR_GOVERNANCE" == true ]]; then
  tpl="$(solar_core_dir)/templates/workspace-AGENTS.md"
  if [[ -f "$tpl" ]]; then
    if [[ -f "$SOLAR_WORKSPACE/AGENTS.md" ]]; then
      cp "$SOLAR_WORKSPACE/AGENTS.md" "$SOLAR_WORKSPACE/AGENTS.md.bak.$(date +%Y%m%d%H%M%S)"
    fi
    cp "$tpl" "$SOLAR_WORKSPACE/AGENTS.md"
    echo "OK: replaced AGENTS.md from template"
  fi
  for name in CLAUDE.md GEMINI.md .cursorrules; do
    rm -f "$SOLAR_WORKSPACE/$name"
    ln -snf AGENTS.md "$SOLAR_WORKSPACE/$name" 2>/dev/null || true
  done
  echo "OK: refreshed IDE governance symlinks"
fi

if [[ "$SKIP_PRUNE_INSTALL" != true ]] && ! solar_client_paths_equal "$SOLAR_ROOT" "$SOLAR_WORKSPACE"; then
  solar_client_prune_install_root "$SOLAR_ROOT" false
fi

echo ""
echo "Next steps:"
echo "  solar client sync"
echo "  solar client doctor"
echo "  bash \"$(solar_core_dir)/scripts/smoke-solar-client.sh\" \"$SOLAR_ROOT\""
if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "  bash \"$(solar_core_dir)/skills/solar-system/scripts/install_launchagent_macos.sh\""
fi
