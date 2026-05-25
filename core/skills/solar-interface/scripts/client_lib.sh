#!/usr/bin/env bash
# client_lib.sh — shared Solar Client workspace helpers (v1.1).
set -euo pipefail

_CLIENT_LIB_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_paths.sh
source "$_CLIENT_LIB_SCRIPT_DIR/resolve_solar_paths.sh"

solar_client_install_root() {
  _resolve_global_root
}

solar_client_git_identity() {
  local client_root="$1"
  local git_root version commit
  git_root="$(_resolve_abs "$client_root")"
  if git -C "$git_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    version="$(git -C "$git_root" describe --tags --always 2>/dev/null || echo "dev")"
    commit="$(git -C "$git_root" rev-parse HEAD 2>/dev/null || echo "unknown")"
  else
    version="dev"
    commit="unknown"
  fi
  printf '%s %s\n' "$version" "$commit"
}

solar_client_write_manifest_v11() {
  local workspace="$1"
  local client_root="$2"
  local preserve_synced="${3:-}"
  local version commit synced_at
  read -r version commit < <(solar_client_git_identity "$client_root")
  synced_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  if [[ -n "$preserve_synced" && -f "$workspace/.solar/manifest.json" ]]; then
    local existing
    existing="$(python3 - <<'PY' "$workspace/.solar/manifest.json"
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("synced_at", ""))
except Exception:
    print("")
PY
)" || existing=""
    if [[ -n "$existing" ]]; then
      synced_at="$existing"
    fi
  fi
  mkdir -p "$workspace/.solar"
  python3 - <<PY "$workspace/.solar/manifest.json" "$version" "$commit" "$synced_at"
import json, sys
path, version, commit, synced_at = sys.argv[1:5]
data = {
    "layout": "solar-client-v1.1",
    "client_version": version,
    "core_version": version,
    "core_commit": commit,
    "governance_seed": f"workspace-AGENTS@{version}",
    "channel": "stable",
    "synced_at": synced_at,
    "core_source": "global",
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

solar_client_manifest_core_version() {
  local manifest="$1"
  python3 - <<'PY' "$manifest" 2>/dev/null || echo ""
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("core_version") or data.get("version") or "")
except Exception:
    print("")
PY
}

solar_client_touch_manifest_synced() {
  local workspace="$1"
  local manifest="$workspace/.solar/manifest.json"
  [[ -f "$manifest" ]] || return 0
  python3 - <<'PY' "$manifest"
import json, sys
from datetime import datetime, timezone
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data["synced_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
core = data.get("core_version") or data.get("version")
if core:
    data["core_version"] = core
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

solar_client_paths_equal() {
  local a b
  a="$(_resolve_abs "$1" 2>/dev/null || echo "$1")"
  b="$(_resolve_abs "$2" 2>/dev/null || echo "$2")"
  [[ "$a" == "$b" ]]
}

solar_client_workspace_layout() {
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

solar_client_install_prune_denylist() {
  printf '%s\n' .claude .codex .cursor .gemini .vscode sun .env .pytest_cache .DS_Store
}

solar_client_list_install_artifacts() {
  local root="$1"
  local name
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    if [[ -e "$root/$name" ]]; then
      echo "$root/$name"
    fi
  done < <(solar_client_install_prune_denylist)
}

solar_client_prune_install_root() {
  local root="$1"
  local dry_run="${2:-false}"
  local path
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    if [[ "$dry_run" == true ]]; then
      echo "would remove: $path"
    else
      rm -rf "$path"
      echo "OK: removed $path"
    fi
  done < <(solar_client_list_install_artifacts "$root")
}

solar_client_print_upgrade_report() {
  local ws="$1"
  local root="$2"
  local layout manifest_layout git_ver git_commit
  layout="$(solar_client_workspace_layout "$ws" 2>/dev/null || echo "unknown")"
  read -r git_ver git_commit < <(solar_client_git_identity "$root")
  manifest_layout=""
  if [[ -f "$ws/.solar/manifest.json" ]]; then
    manifest_layout="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("layout",""))' "$ws/.solar/manifest.json" 2>/dev/null || true)"
  fi
  echo "Solar Client upgrade"
  echo "  SOLAR_WORKSPACE=$ws"
  echo "  SOLAR_ROOT=$root"
  echo "  workspace_layout=$layout"
  echo "  install_git=$git_ver (${git_commit:0:12})"
  echo "  manifest.layout=${manifest_layout:-<none>}"
  if [[ "$git_ver" == v0.8.* ]] || [[ "$git_ver" == v0.9.* ]]; then
    echo "  HINT: update framework repo: cd \"$root\" && git fetch && git checkout v0.10.0"
  fi
}

solar_client_restructure_needed() {
  local ws="$1"
  local layout
  layout="$(solar_client_workspace_layout "$ws" 2>/dev/null || return 1)"
  [[ "$layout" == "legacy_root" ]] || return 1
  [[ ! -d "$ws/solar/core" ]]
}

solar_client_restructure_plan() {
  local ws="$1"
  solar_client_restructure_needed "$ws" || return 1
  echo "mkdir -p $ws/solar"
  echo "mv $ws/core $ws/solar/core"
  if [[ -d "$ws/.git" ]]; then
    echo "mv $ws/.git $ws/solar/.git"
  fi
}

solar_client_restructure_apply() {
  local ws="$1"
  local dry_run="${2:-false}"
  local backup=""

  if ! solar_client_restructure_needed "$ws"; then
    if [[ -d "$ws/solar/core" ]]; then
      echo "INFO: restructure skipped (already has solar/core/)"
    else
      echo "INFO: restructure skipped (workspace layout is not legacy_root monorepo)"
    fi
    return 0
  fi

  if [[ "$dry_run" == true ]]; then
    solar_client_restructure_plan "$ws" | while read -r line; do
      echo "  would: $line"
    done
    return 0
  fi

  backup="${ws}.pre-upgrade.$(date +%Y%m%d%H%M%S)"
  echo "OK: backup workspace tree at $backup (cp -a; may take a moment)"
  cp -a "$ws" "$backup"

  mkdir -p "$ws/solar"
  mv "$ws/core" "$ws/solar/core"
  echo "OK: moved core/ -> solar/core/"
  if [[ -d "$ws/.git" && ! -e "$ws/solar/.git" ]]; then
    mv "$ws/.git" "$ws/solar/.git"
    echo "OK: moved .git -> solar/.git"
  fi
}
