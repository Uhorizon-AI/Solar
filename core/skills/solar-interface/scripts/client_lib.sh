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

solar_client_manifest_core_commit() {
  local manifest="$1"
  python3 - <<'PY' "$manifest" 2>/dev/null || echo ""
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("core_commit") or "")
except Exception:
    print("")
PY
}

# After sync: align manifest core_version/client_version/core_commit with SOLAR_ROOT.
solar_client_bump_manifest_from_install() {
  local workspace="$1"
  local client_root="$2"
  local manifest="$workspace/.solar/manifest.json"
  [[ -f "$manifest" ]] || return 0
  local version commit
  read -r version commit < <(solar_client_git_identity "$client_root")
  python3 - <<PY "$manifest" "$version" "$commit"
import json, sys
path, version, commit = sys.argv[1:4]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data["core_version"] = version
data["client_version"] = version
data["core_commit"] = commit
data["core_source"] = "global"
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
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

solar_client_backups_dir() {
  echo "$1/backups"
}

solar_client_backup_label() {
  local version="$1"
  version="${version#v}"
  version="${version//\//-}"
  echo "${version}-$(date +%Y%m%d-%H%M%S)"
}

solar_client_rotate_backups() {
  local root="$1"
  local keep="${2:-5}"
  local bdir
  bdir="$(solar_client_backups_dir "$root")"
  [[ -d "$bdir" ]] || return 0
  local count=0
  while IFS= read -r dir; do
    [[ -n "$dir" ]] || continue
    count=$((count + 1))
    if [[ "$count" -gt "$keep" ]]; then
      rm -rf "$dir"
      echo "OK: pruned old backup $dir"
    fi
  done < <(
    find "$bdir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | while IFS= read -r d; do
      [[ -n "$d" ]] || continue
      if stat -c '%Y' "$d" >/dev/null 2>&1; then
        printf '%s\t%s\n' "$(stat -c '%Y' "$d")" "$d"
      else
        printf '%s\t%s\n' "$(stat -f '%m' "$d" 2>/dev/null || echo 0)" "$d"
      fi
    done | sort -t$'\t' -k1 -rn | cut -f2-
  )
}

solar_client_backup_install_git() {
  local root="$1"
  local version="$2"
  local label dest
  label="$(solar_client_backup_label "$version")"
  dest="$(solar_client_backups_dir "$root")/$label"
  mkdir -p "$(dirname "$dest")"
  # Full install tree (including .git/objects) for restorable SOLAR_ROOT snapshots.
  rsync -a \
    --exclude 'backups' \
    "$root/" "$dest/"
  echo "$dest"
}

solar_client_backup_install_core() {
  local root="$1"
  local version="$2"
  local label dest
  label="$(solar_client_backup_label "$version")"
  dest="$(solar_client_backups_dir "$root")/$label/core"
  mkdir -p "$dest"
  if [[ -d "$root/core" ]]; then
    rsync -a "$root/core/" "$dest/"
  fi
  echo "$(solar_client_backups_dir "$root")/$label"
}

solar_client_git_dirty() {
  local root="$1"
  git -C "$root" diff --quiet 2>/dev/null && git -C "$root" diff --cached --quiet 2>/dev/null
}

solar_client_git_fetch() {
  local root="$1"
  if git -C "$root" remote get-url origin >/dev/null 2>&1; then
    git -C "$root" fetch --tags origin
  else
    git -C "$root" fetch --tags 2>/dev/null || true
  fi
}

solar_client_git_remote_tag_version() {
  local root="$1"
  local ref="${2:-}"
  if [[ -z "$ref" ]]; then
    git -C "$root" describe --tags origin/main 2>/dev/null \
      || git -C "$root" describe --tags origin/master 2>/dev/null \
      || git -C "$root" describe --tags --abbrev=0 2>/dev/null \
      || echo ""
  else
    git -C "$root" describe --tags "$ref" 2>/dev/null || echo "$ref"
  fi
}

solar_client_apply_git_update() {
  local root="$1"
  local tag="${2:-}"
  local yes="${3:-false}"

  if ! git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: SOLAR_ROOT is not a git repository: $root" >&2
    return 1
  fi

  if ! solar_client_git_dirty "$root"; then
    echo "WARN: SOLAR_ROOT has uncommitted changes"
    if [[ "$yes" != true ]]; then
      echo "ERROR: re-run with --yes to update anyway" >&2
      return 1
    fi
  fi

  solar_client_git_fetch "$root"

  if [[ -n "$tag" ]]; then
    if ! git -C "$root" rev-parse "$tag^{commit}" >/dev/null 2>&1; then
      echo "ERROR: tag/ref not found after fetch: $tag" >&2
      return 1
    fi
    git -C "$root" checkout "$tag"
  else
    if git -C "$root" show-ref --verify --quiet refs/remotes/origin/main; then
      git -C "$root" checkout main 2>/dev/null || git -C "$root" checkout -B main
      git -C "$root" pull --ff-only origin main
    elif git -C "$root" show-ref --verify --quiet refs/remotes/origin/master; then
      git -C "$root" checkout master 2>/dev/null || git -C "$root" checkout -B master
      git -C "$root" pull --ff-only origin master
    else
      echo "WARN: no origin/main or origin/master; staying on current branch"
    fi
  fi
  return 0
}

solar_client_apply_bundle_update() {
  local root="$1"
  local from_dev="${2:-true}"
  local from_tag="${3:-}"
  local bundle_script="$4"

  local tmpdir
  tmpdir="$(mktemp -d)"

  local -a bundle_args=(--output "$tmpdir" --force)
  if [[ -n "$from_tag" ]]; then
    bundle_args+=(--from-tag "$from_tag")
  else
    bundle_args+=(--from-dev)
  fi

  bash "$bundle_script" "${bundle_args[@]}"
  mkdir -p "$root/core"
  rsync -a --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude 'node_modules' \
    "$tmpdir/core/" "$root/core/"
  rm -rf "$tmpdir"
}

solar_client_manifest_needs_repair() {
  local manifest="$1"
  [[ -f "$manifest" ]] || return 0
  if grep -q '^<<<<<<<' "$manifest" 2>/dev/null; then
    return 0
  fi
  python3 - <<'PY' "$manifest"
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)  # needs repair
layout = data.get("layout", "")
core = data.get("core_version") or data.get("version") or ""
if layout != "solar-client-v1.1" or not core:
    sys.exit(0)
sys.exit(1)
PY
}

solar_client_repair_manifest() {
  local workspace="$1"
  local install_root="$2"
  solar_client_write_manifest_v11 "$workspace" "$install_root" preserve_synced=1
}

solar_client_update_check_report() {
  local install_root="$1"
  local workspace="${2:-}"

  read -r gv gc < <(solar_client_git_identity "$install_root")
  echo "Global Solar Client (SOLAR_ROOT):"
  echo "  path=$install_root"
  echo "  version=$gv commit=${gc:0:12}"

  if [[ -d "$install_root/.git" ]]; then
    solar_client_git_fetch "$install_root" 2>/dev/null || true
    local remote_ver
    remote_ver="$(solar_client_git_remote_tag_version "$install_root" "")"
    if [[ -n "$remote_ver" && "$remote_ver" != "$gv" ]]; then
      echo "  remote_available=$remote_ver"
      echo "  HINT: solar client update --tag $remote_ver"
    fi
  fi

  if [[ -n "$workspace" && -f "$workspace/.solar/manifest.json" ]]; then
    local mv
    mv="$(solar_client_manifest_core_version "$workspace/.solar/manifest.json")"
    echo "Workspace manifest core_version=${mv:-<none>}"
    if [[ -n "$mv" && "$gv" != "$mv" && "$gv" != dev* ]]; then
      echo "WARN: global client updated — run: solar client sync"
    fi
    if solar_client_manifest_needs_repair "$workspace/.solar/manifest.json"; then
      echo "WARN: manifest may need repair — run: solar client update --repair"
    fi
  elif [[ -n "$workspace" ]]; then
    echo "Workspace manifest=<none>"
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
