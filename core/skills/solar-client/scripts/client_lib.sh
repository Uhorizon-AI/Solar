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
    "requires_global_client": True,
    "portable_capabilities": [],
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
if data.get("core_source") != "workspace-snapshot":
    data["core_source"] = "global"
    data["requires_global_client"] = True
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

# Workspace entries that stay at SOLAR_WORKSPACE root (runtime / client metadata).
solar_client_restructure_should_keep() {
  local base="$1"
  case "$base" in
    sun|planets|.solar|solar|scratch|.DS_Store|.pytest_cache) return 0 ;;
    .env|.env.clean|.env.mac) return 0 ;;
    .claude|.codex|.cursor|.gemini|.vscode) return 0 ;;
  esac
  [[ "$base" == .venv* ]] && return 0
  [[ "$base" == *.pre-upgrade.* ]] && return 0
  return 1
}

# True when framework/install artifacts still live at workspace root (not workspace governance).
# Root AGENTS.md from client init is workspace governance and must not count as framework.
solar_client_framework_at_workspace_root() {
  local ws="$1"
  [[ -d "$ws/core" && -f "$ws/core/AGENTS.md" ]] && return 0
  [[ -d "$ws/.git" && ! -d "$ws/solar/.git" ]] && return 0
  [[ -d "$ws/.github" && ! -d "$ws/solar/.github" ]] && return 0
  [[ -f "$ws/CHANGELOG.md" && ! -f "$ws/solar/CHANGELOG.md" ]] && return 0
  return 1
}

solar_client_restructure_complete() {
  local ws="$1"
  [[ -d "$ws/solar/core" && -f "$ws/solar/core/AGENTS.md" ]] \
    && ! solar_client_framework_at_workspace_root "$ws"
}

solar_client_restructure_needed() {
  local ws="$1"
  solar_client_restructure_complete "$ws" && return 1
  solar_client_framework_at_workspace_root "$ws"
}

solar_client_restructure_iter_entries() {
  local ws="$1"
  local entry base
  shopt -s nullglob
  for entry in "$ws"/* "$ws"/.[!.]* "$ws"/..?*; do
    [[ -e "$entry" ]] || continue
    base="$(basename "$entry")"
    solar_client_restructure_should_keep "$base" && continue
    if [[ -e "$ws/solar/$base" ]]; then
      echo "WARN: skip $base (already exists under solar/)" >&2
      continue
    fi
    printf '%s\n' "$entry"
  done
  shopt -u nullglob
}

solar_client_restructure_plan() {
  local ws="$1"
  solar_client_restructure_needed "$ws" || return 1
  echo "mkdir -p $ws/solar"
  local entry
  while IFS= read -r entry; do
    [[ -n "$entry" ]] || continue
    echo "mv $entry $ws/solar/"
  done < <(solar_client_restructure_iter_entries "$ws")
}

# Install snapshots: nested layout (workspace + solar/ child) → $SOLAR_WORKSPACE/backups.
solar_client_backups_dir() {
  local install_root="$1"
  local workspace="${2:-}"
  install_root="$(_resolve_abs "$install_root" 2>/dev/null || echo "$install_root")"
  if [[ -n "$workspace" ]]; then
    workspace="$(_resolve_abs "$workspace" 2>/dev/null || echo "$workspace")"
    if [[ "$install_root" != "$workspace" && "$install_root" == "$workspace/"* ]]; then
      echo "$workspace/backups"
      return 0
    fi
  fi
  echo "$install_root/backups"
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
  local workspace="${3:-}"
  local bdir
  bdir="$(solar_client_backups_dir "$root" "$workspace")"
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
  local workspace="${3:-}"
  local label dest
  label="$(solar_client_backup_label "$version")"
  dest="$(solar_client_backups_dir "$root" "$workspace")/$label"
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
  local workspace="${3:-}"
  local label dest
  label="$(solar_client_backup_label "$version")"
  dest="$(solar_client_backups_dir "$root" "$workspace")/$label/core"
  mkdir -p "$dest"
  if [[ -d "$root/core" ]]; then
    rsync -a "$root/core/" "$dest/"
  fi
  echo "$(solar_client_backups_dir "$root" "$workspace")/$label"
}

solar_client_git_dirty() {
  local root="$1"
  git -C "$root" diff --quiet 2>/dev/null && git -C "$root" diff --cached --quiet 2>/dev/null
}

# Fase 2.1: git install — rsync snapshot only with explicit --backup (rollback = git tags).
solar_client_should_rsync_backup_git() {
  local _root="$1"
  local force_backup="${2:-false}"
  [[ "$force_backup" == true ]]
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

solar_client_manifest_field() {
  local manifest="$1"
  local field="$2"
  python3 - <<'PY' "$manifest" "$field" 2>/dev/null || echo ""
import json, sys
path, field = sys.argv[1:3]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    val = data.get(field, "")
    if isinstance(val, bool):
        print("true" if val else "false")
    elif isinstance(val, list):
        print(",".join(str(x) for x in val))
    else:
        print(val or "")
except Exception:
    print("")
PY
}

solar_client_manifest_core_source() {
  solar_client_manifest_field "$1" "core_source"
}

solar_client_bundle_dir() {
  printf '%s/.solar/bundle' "$1"
}

solar_client_bundle_core_dir() {
  printf '%s/core' "$(solar_client_bundle_dir "$1")"
}

solar_client_max_bundle_mb() {
  local from_env="${SOLAR_MAX_BUNDLE_MB:-}"
  if [[ -n "$from_env" && "$from_env" =~ ^[0-9]+$ ]]; then
    echo "$from_env"
    return 0
  fi
  echo "200"
}

solar_client_bundle_size_mb() {
  local bundle_dir="$1"
  [[ -d "$bundle_dir" ]] || { echo "0"; return 0; }
  local bytes
  if du -sk "$bundle_dir" >/dev/null 2>&1; then
    bytes="$(du -sk "$bundle_dir" | awk '{print $1 * 1024}')"
  else
    bytes="$(find "$bundle_dir" -type f -print0 2>/dev/null | xargs -0 stat -f '%z' 2>/dev/null | awk '{s+=$1} END {print s+0}')"
  fi
  python3 - <<PY "$bytes"
import sys
b = int(sys.argv[1] or 0)
print(f"{b / (1024*1024):.2f}")
PY
}

solar_client_check_snapshot_outdated() {
  local workspace="$1"
  local install_root="${2:-}"
  local manifest="$workspace/.solar/manifest.json"
  [[ -f "$manifest" ]] || return 1
  [[ "$(solar_client_manifest_core_source "$manifest")" == "workspace-snapshot" ]] || return 1
  local bundle_ver global_ver
  bundle_ver="$(solar_client_manifest_core_version "$manifest")"
  if [[ -n "$install_root" ]] && _resolve_is_workspace_bundle_root "$install_root" "$workspace" 2>/dev/null; then
    install_root=""
  fi
  if [[ -z "$install_root" ]]; then
    install_root="$(solar_global_install_root 2>/dev/null || true)"
  fi
  [[ -n "$install_root" ]] || return 1
  read -r global_ver _ < <(solar_client_git_identity "$install_root")
  [[ -n "$bundle_ver" && -n "$global_ver" && "$bundle_ver" != "$global_ver" && "$global_ver" != dev* ]]
}

solar_client_write_manifest_portable() {
  local workspace="$1"
  local bundle_checksum="$2"
  local capabilities="${3:-}"
  local manifest="$workspace/.solar/manifest.json"
  local snapshot_at synced_at existing_ver existing_commit global_root
  snapshot_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  synced_at="$snapshot_at"
  existing_ver=""
  existing_commit=""
  if [[ -f "$manifest" ]]; then
    synced_at="$(solar_client_manifest_field "$manifest" synced_at)"
    [[ -n "$synced_at" ]] || synced_at="$snapshot_at"
  fi
  if global_root="$(solar_global_install_root 2>/dev/null || true)" && [[ -n "$global_root" ]]; then
    read -r existing_ver existing_commit < <(solar_client_git_identity "$global_root")
  elif [[ -f "$manifest" ]]; then
    existing_ver="$(solar_client_manifest_core_version "$manifest")"
    existing_commit="$(solar_client_manifest_core_commit "$manifest")"
  fi
  python3 - <<PY "$manifest" "$bundle_checksum" "$snapshot_at" "$synced_at" "$existing_ver" "$existing_commit" "$capabilities"
import json, sys
path, checksum, snapshot_at, synced_at, ver, commit, caps = sys.argv[1:8]
caps_list = [c.strip() for c in caps.split(",") if c.strip()] if caps else []
data = {}
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    pass
data.update({
    "layout": "solar-client-v1.1",
    "core_source": "workspace-snapshot",
    "requires_global_client": False,
    "portable_capabilities": caps_list,
    "bundle_path": ".solar/bundle",
    "bundle_checksum": checksum,
    "snapshot_at": snapshot_at,
    "snapshot_outdated": False,
    "synced_at": synced_at,
    "channel": data.get("channel") or "stable",
})
if ver:
    data["core_version"] = ver
    data["client_version"] = ver
if commit:
    data["core_commit"] = commit
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

solar_client_mark_snapshot_outdated() {
  local manifest="$1"
  local outdated="${2:-true}"
  [[ -f "$manifest" ]] || return 0
  python3 - <<PY "$manifest" "$outdated"
import json, sys
path, outdated = sys.argv[1], sys.argv[2] == "true"
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data["snapshot_outdated"] = outdated
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

solar_client_bundle_validate() {
  local workspace="$1"
  local strict="${2:-false}"
  local bundle_dir manifest index checksums
  bundle_dir="$(solar_client_bundle_dir "$workspace")"
  manifest="$workspace/.solar/manifest.json"
  index="$bundle_dir/index.json"
  checksums="$bundle_dir/checksums.sha256"

  [[ -d "$bundle_dir" ]] || { echo "missing bundle directory"; return 1; }
  [[ -f "$index" ]] || { echo "missing index.json"; return 1; }
  [[ -f "$checksums" ]] || { echo "missing checksums.sha256"; return 1; }
  [[ -d "$bundle_dir/core/skills" ]] || { echo "missing bundle core/skills/"; return 1; }

  python3 - <<'PY' "$index" "$checksums" "$bundle_dir" "$strict"
import hashlib, json, os, sys

index_path, sums_path, bundle_dir, strict = sys.argv[1:5]
strict = strict == "true"

with open(index_path, encoding="utf-8") as fh:
    index = json.load(fh)

entries = index.get("files") or index.get("entries") or []
if not entries:
    print("index.json has no file entries")
    sys.exit(1)

expected = {}
if os.path.isfile(sums_path):
    with open(sums_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                expected[parts[1]] = parts[0]

missing = []
bad = []
for item in entries:
    rel = item.get("path") or item.get("rel") or ""
    if not rel:
        continue
    full = os.path.join(bundle_dir, rel)
    if not os.path.isfile(full):
        missing.append(rel)
        continue
    if rel in expected:
        h = hashlib.sha256()
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() != expected[rel]:
            bad.append(rel)

if missing:
    print("missing bundled files: " + ", ".join(missing[:5]))
    sys.exit(1)
if bad:
    print("checksum mismatch: " + ", ".join(bad[:5]))
    sys.exit(1)

if strict:
    for item in entries:
        rel = item.get("path") or item.get("rel") or ""
        base = os.path.basename(rel)
        if base == ".env" or base.endswith(".env") or "/.env" in rel:
            print(f"secret denylist: {rel}")
            sys.exit(1)
PY
}

solar_client_bundle_scan_secrets() {
  local workspace="$1"
  local bundle_dir
  bundle_dir="$(solar_client_bundle_dir "$workspace")"
  [[ -f "$bundle_dir/index.json" ]] || return 0
  python3 - <<'PY' "$bundle_dir/index.json" "$bundle_dir"
import json, os, re, sys
index_path, bundle_dir = sys.argv[1:3]
with open(index_path, encoding="utf-8") as fh:
    entries = json.load(fh).get("files") or []
literal_pat = re.compile(r"sk-(?:ant|proj)-[a-z0-9-]{20,}")
found = []
for item in entries:
    rel = item.get("path") or ""
    if rel.endswith(".env") or "/.env" in rel:
        found.append(rel)
        continue
    full = os.path.join(bundle_dir, rel)
    if not os.path.isfile(full):
        continue
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
        if literal_pat.search(text):
            found.append(f"{rel}:literal-token")
    except OSError:
        pass
for f in found:
    print(f)
PY
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
    local mv core_src
    mv="$(solar_client_manifest_core_version "$workspace/.solar/manifest.json")"
    core_src="$(solar_client_manifest_core_source "$workspace/.solar/manifest.json")"
    echo "Workspace manifest core_version=${mv:-<none>} core_source=${core_src:-global}"
    if [[ "$core_src" == "workspace-snapshot" ]]; then
      if solar_client_check_snapshot_outdated "$workspace" "$install_root"; then
        echo "WARN: workspace bundle snapshot_outdated (global=$gv bundle=$mv) — run: solar client bundle create"
        solar_client_mark_snapshot_outdated "$workspace/.solar/manifest.json" true
      fi
    fi
    if [[ -n "$mv" && "$gv" != "$mv" && "$gv" != dev* && "$core_src" == "global" ]]; then
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
    if solar_client_restructure_complete "$ws"; then
      echo "INFO: restructure skipped (full install already under solar/)"
    else
      echo "INFO: restructure skipped (no framework files at workspace root)"
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
  local entry base moved=0
  while IFS= read -r entry; do
    [[ -n "$entry" ]] || continue
    base="$(basename "$entry")"
    mv "$entry" "$ws/solar/"
    echo "OK: moved $base -> solar/"
    moved=$((moved + 1))
  done < <(solar_client_restructure_iter_entries "$ws")

  if [[ "$moved" -eq 0 ]]; then
    echo "WARN: restructure found nothing to move (check solar/ for conflicts)" >&2
    return 1
  fi
}
