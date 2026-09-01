#!/usr/bin/env bash
# client_lib.sh — shared Solar Client workspace helpers (v1.1).
set -euo pipefail

_CLIENT_LIB_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_paths.sh
source "$_CLIENT_LIB_SCRIPT_DIR/resolve_solar_paths.sh"

solar_client_install_root() {
  _resolve_global_root
}

# Canonical public framework repo (install / bootstrap / docs).
solar_client_canonical_repo_url() {
  printf '%s\n' "${SOLAR_REPO_URL:-https://github.com/Uhorizon-AI/Solar.git}"
}

# Default global install root (Claude/Codex-style: hidden data dir, not ~/Solar/solar).
# Override with SOLAR_ROOT, SOLAR_INSTALL_DIR, or install --install-dir.
solar_client_default_install_dir() {
  if [[ -n "${SOLAR_ROOT:-}" ]]; then
    printf '%s\n' "$SOLAR_ROOT"
    return 0
  fi
  if [[ -n "${SOLAR_INSTALL_DIR:-}" ]]; then
    printf '%s\n' "$SOLAR_INSTALL_DIR"
    return 0
  fi
  printf '%s\n' "${HOME}/.local/share/solar"
}

solar_client_releases_latest_api() {
  printf '%s\n' "${SOLAR_RELEASES_API_URL:-https://api.github.com/repos/Uhorizon-AI/Solar/releases/latest}"
}

# Resolve latest stable GitHub Release tag_name via curl + JSON parse.
# Override for tests/offline: SOLAR_STABLE_RELEASE_TAG=vX.Y.Z
# Returns tag on stdout; exit 1 on failure (no fallback to main).
solar_client_resolve_stable_release_tag() {
  if [[ -n "${SOLAR_STABLE_RELEASE_TAG:-}" ]]; then
    local forced="${SOLAR_STABLE_RELEASE_TAG}"
    if [[ ! "$forced" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-].+)?$ ]]; then
      echo "ERROR: SOLAR_STABLE_RELEASE_TAG invalid: $forced" >&2
      return 1
    fi
    # Reject prerelease-looking overrides unless explicitly allowed
    if [[ "$forced" =~ (beta|rc|alpha|pre) ]] && [[ "${SOLAR_ALLOW_PRERELEASE:-}" != "1" ]]; then
      echo "ERROR: refusing prerelease tag as stable: $forced (set SOLAR_ALLOW_PRERELEASE=1 to override)" >&2
      return 1
    fi
    printf '%s\n' "$forced"
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required to resolve the stable Solar release" >&2
    return 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required to resolve the stable Solar release" >&2
    return 1
  fi

  local api_url body tag
  api_url="$(solar_client_releases_latest_api)"
  if ! body="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api_url" 2>/dev/null)"; then
    echo "ERROR: failed to fetch stable release from $api_url" >&2
    return 1
  fi

  tag="$(printf '%s' "$body" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception as exc:
    sys.stderr.write(f"ERROR: invalid releases API JSON: {exc}\n")
    sys.exit(1)
if data.get("draft"):
    sys.stderr.write("ERROR: latest release is a draft\n")
    sys.exit(1)
if data.get("prerelease"):
    sys.stderr.write("ERROR: latest release is a prerelease; no stable channel available\n")
    sys.exit(1)
tag = (data.get("tag_name") or "").strip()
if not tag:
    sys.stderr.write("ERROR: releases API response missing tag_name\n")
    sys.exit(1)
print(tag)
')" || return 1

  if [[ -z "$tag" ]]; then
    echo "ERROR: empty stable release tag" >&2
    return 1
  fi
  printf '%s\n' "$tag"
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

# Prefer settings.json; fall back to legacy manifest.json for reads.
# If neither exists, returns the canonical write path (.solar/settings.json).
solar_client_settings_path() {
  local workspace="$1"
  if [[ -f "$workspace/.solar/settings.json" ]]; then
    printf '%s\n' "$workspace/.solar/settings.json"
  elif [[ -f "$workspace/.solar/manifest.json" ]]; then
    printf '%s\n' "$workspace/.solar/manifest.json"
  else
    printf '%s\n' "$workspace/.solar/settings.json"
  fi
}

solar_client_settings_exists() {
  local workspace="$1"
  [[ -f "$workspace/.solar/settings.json" || -f "$workspace/.solar/manifest.json" ]]
}

# Canonical write target (always settings.json under layout v1.2).
solar_client_settings_write_path() {
  printf '%s\n' "$1/.solar/settings.json"
}

# Print sync_exclude_planets one per line (empty if absent/[]).
solar_client_read_sync_exclude_planets() {
  local workspace="$1"
  local path
  path="$(solar_client_settings_path "$workspace")"
  [[ -f "$path" ]] || return 0
  python3 - <<'PY' "$path"
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception as exc:
    sys.stderr.write(f"ERROR: invalid Solar workspace settings: {path}: {exc}\n")
    sys.exit(1)
if not isinstance(data, dict):
    sys.stderr.write(f"ERROR: Solar workspace settings must be a JSON object: {path}\n")
    sys.exit(1)
planets = data.get("sync_exclude_planets", [])
if not isinstance(planets, list):
    sys.stderr.write(f"ERROR: sync_exclude_planets must be an array of planet names: {path}\n")
    sys.exit(1)
for p in planets:
    if not isinstance(p, str) or not p.strip() or "/" in p or "\\" in p or p in (".", ".."):
        sys.stderr.write(f"ERROR: invalid planet name in sync_exclude_planets: {p!r}\n")
        sys.exit(1)
    print(p.strip())
PY
}

# Replace sync_exclude_planets with the given list (args after workspace).
# Empty list → write "sync_exclude_planets": [] (key kept).
solar_client_write_sync_exclude_planets() {
  local workspace="$1"
  shift
  local write_path read_path
  write_path="$(solar_client_settings_write_path "$workspace")"
  read_path="$(solar_client_settings_path "$workspace")"
  mkdir -p "$workspace/.solar"
  python3 - <<'PY' "$write_path" "$read_path" "$@"
import json, os, sys, tempfile

write_path, read_path = sys.argv[1], sys.argv[2]
planets = []
seen = set()
for planet in sys.argv[3:]:
    planet = planet.strip()
    if not planet or "/" in planet or "\\" in planet or planet in (".", ".."):
        sys.stderr.write(f"ERROR: invalid planet name: {planet!r}\n")
        sys.exit(2)
    if planet not in seen:
        seen.add(planet)
        planets.append(planet)

data = {}
if os.path.isfile(read_path):
    try:
        with open(read_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        sys.stderr.write(f"ERROR: invalid Solar workspace settings: {read_path}: {exc}\n")
        sys.exit(1)
    if not isinstance(data, dict):
        sys.stderr.write(f"ERROR: Solar workspace settings must be a JSON object: {read_path}\n")
        sys.exit(1)

data["sync_exclude_planets"] = planets
data["scope"] = "workspace"
data["layout"] = "solar-client-v1.2"

os.makedirs(os.path.dirname(write_path), exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=os.path.dirname(write_path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, write_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

legacy = os.path.join(os.path.dirname(write_path), "manifest.json")
if os.path.isfile(legacy) and os.path.realpath(legacy) != os.path.realpath(write_path):
    os.unlink(legacy)
PY
}

# Writes .solar/settings.json (layout solar-client-v1.2). Prefer this name over the legacy alias.
solar_client_write_settings_v12() {
  local workspace="$1"
  local client_root="$2"
  local preserve_synced="${3:-}"
  local version commit synced_at write_path read_path
  read -r version commit < <(solar_client_git_identity "$client_root")
  synced_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  write_path="$(solar_client_settings_write_path "$workspace")"
  read_path="$(solar_client_settings_path "$workspace")"
  if [[ -n "$preserve_synced" && -f "$read_path" ]]; then
    local existing
    existing="$(python3 - <<'PY' "$read_path"
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
  python3 - <<PY "$write_path" "$read_path" "$version" "$commit" "$synced_at"
import json, os, sys, tempfile

write_path, read_path, version, commit, synced_at = sys.argv[1:6]
managed = {
    "scope": "workspace",
    "layout": "solar-client-v1.2",
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

existing = {}
if os.path.isfile(read_path):
    try:
        with open(read_path, encoding="utf-8") as fh:
            existing = json.load(fh)
    except Exception:
        existing = {}

data = dict(existing)
data.update(managed)

os.makedirs(os.path.dirname(write_path), exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=os.path.dirname(write_path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    # Test hook: fail after temp write, before commit — legacy must remain.
    if os.environ.get("SOLAR_CLIENT_TEST_FAIL_BEFORE_REPLACE") == "1":
        raise RuntimeError("injected fail before replace")
    os.replace(tmp, write_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

# Delete legacy only after settings.json is committed.
legacy = os.path.join(os.path.dirname(write_path), "manifest.json")
if os.path.isfile(legacy) and os.path.realpath(legacy) != os.path.realpath(write_path):
    os.unlink(legacy)
PY
}

# Deprecated alias (writes v1.2 settings.json). Prefer solar_client_write_settings_v12.
solar_client_write_manifest_v11() {
  solar_client_write_settings_v12 "$@"
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

# After sync: align settings core_version/client_version/core_commit with SOLAR_ROOT.
solar_client_bump_manifest_from_install() {
  local workspace="$1"
  local client_root="$2"
  local read_path write_path
  read_path="$(solar_client_settings_path "$workspace")"
  write_path="$(solar_client_settings_write_path "$workspace")"
  [[ -f "$read_path" ]] || return 0
  local version commit
  read -r version commit < <(solar_client_git_identity "$client_root")
  python3 - <<PY "$write_path" "$read_path" "$version" "$commit"
import json, os, sys, tempfile
write_path, read_path, version, commit = sys.argv[1:5]
with open(read_path, encoding="utf-8") as fh:
    data = json.load(fh)
if not isinstance(data, dict):
    raise ValueError(f"Solar workspace settings must be a JSON object: {read_path}")
data["core_version"] = version
data["client_version"] = version
data["core_commit"] = commit
data["scope"] = "workspace"
data["layout"] = "solar-client-v1.2"
if data.get("core_source") != "workspace-snapshot":
    data["core_source"] = "global"
    data["requires_global_client"] = True
os.makedirs(os.path.dirname(write_path), exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=os.path.dirname(write_path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, write_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
legacy = os.path.join(os.path.dirname(write_path), "manifest.json")
if os.path.isfile(legacy) and os.path.realpath(legacy) != os.path.realpath(write_path):
    os.unlink(legacy)
PY
}

solar_client_touch_manifest_synced() {
  local workspace="$1"
  local read_path write_path
  read_path="$(solar_client_settings_path "$workspace")"
  write_path="$(solar_client_settings_write_path "$workspace")"
  [[ -f "$read_path" ]] || return 0
  python3 - <<'PY' "$write_path" "$read_path"
import json, os, sys, tempfile
from datetime import datetime, timezone
write_path, read_path = sys.argv[1:3]
with open(read_path, encoding="utf-8") as fh:
    data = json.load(fh)
if not isinstance(data, dict):
    raise ValueError(f"Solar workspace settings must be a JSON object: {read_path}")
data["synced_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
core = data.get("core_version") or data.get("version")
if core:
    data["core_version"] = core
data["scope"] = "workspace"
data["layout"] = "solar-client-v1.2"
os.makedirs(os.path.dirname(write_path), exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=os.path.dirname(write_path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, write_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
legacy = os.path.join(os.path.dirname(write_path), "manifest.json")
if os.path.isfile(legacy) and os.path.realpath(legacy) != os.path.realpath(write_path):
    os.unlink(legacy)
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
  if solar_client_settings_exists "$ws"; then
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
  if solar_client_settings_exists "$ws"; then
    manifest_layout="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("layout",""))' "$(solar_client_settings_path "$ws")" 2>/dev/null || true)"
  fi
  echo "Solar Client upgrade"
  echo "  SOLAR_WORKSPACE=$ws"
  echo "  SOLAR_ROOT=$root"
  echo "  workspace_layout=$layout"
  echo "  install_git=$git_ver (${git_commit:0:12})"
  echo "  settings.layout=${manifest_layout:-<none>}"
  if [[ "$git_ver" == v0.8.* ]] || [[ "$git_ver" == v0.9.* ]]; then
    echo "  HINT: update framework repo: cd \"$root\" && git fetch && git checkout v0.10.0"
  fi
  if [[ -f "$ws/.env" ]]; then
    if grep -Eq '^[[:space:]]*(SOLAR_ROUTER_GEMINI_CMD|SOLAR_AI_GEMINI_CMD)=' "$ws/.env"; then
      echo "  WARN: remove SOLAR_ROUTER_GEMINI_CMD / SOLAR_AI_GEMINI_CMD. Do not rename the value in place (e.g. gemini -y is invalid under AGY). Optional: SOLAR_ROUTER_AGY_CMD=agy -p --dangerously-skip-permissions"
    fi
    if grep -Eiq '^[[:space:]]*(SOLAR_ROUTER_PROVIDER_PRIORITY|SOLAR_AI_PROVIDER_PRIORITY)=.*gemini' "$ws/.env"; then
      echo "  WARN: provider priority lists unsupported gemini — use agy (run solar client update)"
    fi
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
    echo "ERROR: git update requires an explicit ref (stable release or --ref)" >&2
    return 1
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
if layout not in ("solar-client-v1.1", "solar-client-v1.2") or not core:
    sys.exit(0)
sys.exit(1)
PY
}

solar_client_repair_manifest() {
  local workspace="$1"
  local install_root="$2"
  solar_client_write_settings_v12 "$workspace" "$install_root" preserve_synced=1
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
  local manifest
  manifest="$(solar_client_settings_path "$workspace")"
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
  local write_path read_path
  write_path="$(solar_client_settings_write_path "$workspace")"
  read_path="$(solar_client_settings_path "$workspace")"
  local snapshot_at synced_at existing_ver existing_commit global_root
  snapshot_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  synced_at="$snapshot_at"
  existing_ver=""
  existing_commit=""
  mkdir -p "$workspace/.solar"
  if [[ -f "$read_path" ]]; then
    synced_at="$(solar_client_manifest_field "$read_path" synced_at)"
    [[ -n "$synced_at" ]] || synced_at="$snapshot_at"
  fi
  if global_root="$(solar_global_install_root 2>/dev/null || true)" && [[ -n "$global_root" ]]; then
    read -r existing_ver existing_commit < <(solar_client_git_identity "$global_root")
  elif [[ -f "$read_path" ]]; then
    existing_ver="$(solar_client_manifest_core_version "$read_path")"
    existing_commit="$(solar_client_manifest_core_commit "$read_path")"
  fi
  python3 - <<PY "$write_path" "$read_path" "$bundle_checksum" "$snapshot_at" "$synced_at" "$existing_ver" "$existing_commit" "$capabilities"
import json, os, sys, tempfile
write_path, read_path, checksum, snapshot_at, synced_at, ver, commit, caps = sys.argv[1:9]
caps_list = [c.strip() for c in caps.split(",") if c.strip()] if caps else []
data = {}
if os.path.isfile(read_path):
    try:
        with open(read_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        pass
data.update({
    "scope": "workspace",
    "layout": "solar-client-v1.2",
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
os.makedirs(os.path.dirname(write_path), exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=os.path.dirname(write_path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, write_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
legacy = os.path.join(os.path.dirname(write_path), "manifest.json")
if os.path.isfile(legacy) and os.path.realpath(legacy) != os.path.realpath(write_path):
    os.unlink(legacy)
PY
}

solar_client_mark_snapshot_outdated() {
  local workspace="$1"
  local outdated="${2:-true}"
  local read_path write_path
  read_path="$(solar_client_settings_path "$workspace")"
  write_path="$(solar_client_settings_write_path "$workspace")"
  [[ -f "$read_path" ]] || return 0
  python3 - <<PY "$write_path" "$read_path" "$outdated"
import json, os, sys, tempfile
write_path, read_path, outdated = sys.argv[1], sys.argv[2], sys.argv[3] == "true"
with open(read_path, encoding="utf-8") as fh:
    data = json.load(fh)
if not isinstance(data, dict):
    raise ValueError(f"Solar workspace settings must be a JSON object: {read_path}")
data["snapshot_outdated"] = outdated
data["scope"] = "workspace"
data["layout"] = "solar-client-v1.2"
os.makedirs(os.path.dirname(write_path), exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=os.path.dirname(write_path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, write_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
legacy = os.path.join(os.path.dirname(write_path), "manifest.json")
if os.path.isfile(legacy) and os.path.realpath(legacy) != os.path.realpath(write_path):
    os.unlink(legacy)
PY
}

solar_client_bundle_validate() {
  local workspace="$1"
  local strict="${2:-false}"
  local bundle_dir manifest index checksums
  bundle_dir="$(solar_client_bundle_dir "$workspace")"
  manifest="$(solar_client_settings_path "$workspace")"
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

  if [[ -n "$workspace" ]] && solar_client_settings_exists "$workspace"; then
    local mv core_src settings_path
    settings_path="$(solar_client_settings_path "$workspace")"
    mv="$(solar_client_manifest_core_version "$settings_path")"
    core_src="$(solar_client_manifest_core_source "$settings_path")"
    echo "Workspace settings core_version=${mv:-<none>} core_source=${core_src:-global}"
    if [[ "$core_src" == "workspace-snapshot" ]]; then
      if solar_client_check_snapshot_outdated "$workspace" "$install_root"; then
        echo "WARN: workspace bundle snapshot_outdated (global=$gv bundle=$mv) — run: solar client bundle create"
        solar_client_mark_snapshot_outdated "$workspace" true
      fi
    fi
    if [[ -n "$mv" && "$gv" != "$mv" && "$gv" != dev* && "$core_src" == "global" ]]; then
      echo "WARN: global client updated — run: solar client sync"
    fi
    if solar_client_manifest_needs_repair "$settings_path"; then
      echo "WARN: settings may need repair — run: solar client update --repair"
    fi
  elif [[ -n "$workspace" ]]; then
    echo "Workspace settings=<none>"
  fi
}

# LaunchAgent plist path (macOS solar-system supervisor).
solar_client_launchagent_plist_path() {
  printf '%s\n' "${HOME}/Library/LaunchAgents/${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}.plist"
}

# Source solar-system helpers from an install root (post-update tree).
solar_client_source_system_lib() {
  local install_root="$1"
  local lib="${install_root}/core/skills/solar-system/scripts/system_lib.sh"
  [[ -f "$lib" ]] || return 1
  # shellcheck source=/dev/null
  source "$lib"
}

# Classify LaunchAgent SOLAR_ROOT vs install_root.
# Prints one token: skipped_os|no_system_lib|absent|<classify tokens from system_lib>
# Test hook: SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE forces the returned status.
solar_client_assess_launchagent() {
  local install_root="$1"
  local plist status plist_root

  if [[ -n "${SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE:-}" ]]; then
    printf '%s\n' "$SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE"
    return 0
  fi

  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "skipped_os"
    return 0
  fi
  if ! solar_client_source_system_lib "$install_root"; then
    echo "no_system_lib"
    return 0
  fi
  plist="$(solar_client_launchagent_plist_path)"
  if [[ ! -f "$plist" ]]; then
    echo "absent"
    return 0
  fi
  plist_root="$(solar_system_plist_solar_root "$plist" || true)"
  status="$(solar_system_classify_plist_root "$plist_root" "$install_root")"
  printf '%s\n' "$status"
}

# Report / optionally repair LaunchAgent binding after update.
# Args: install_root, reinstall(true|false)
# Returns 0 for read-only report paths; reinstall/install/gateway failures return non-zero.
# Test hooks (optional):
#   SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT — override install_launchagent_macos.sh
#   SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT — override setup_transport_gateway.sh
solar_client_report_launchagent_binding() {
  local install_root="$1"
  local reinstall="${2:-false}"
  local status plist plist_root install_script setup_script

  status="$(solar_client_assess_launchagent "$install_root")"
  case "$status" in
    skipped_os)
      return 0
      ;;
    no_system_lib)
      echo "LaunchAgent: skipped (solar-system helpers missing under install)"
      return 0
      ;;
    absent)
      echo "LaunchAgent: not installed (optional on this machine)"
      return 0
      ;;
    ok)
      echo "LaunchAgent: ok (plist SOLAR_ROOT matches install)"
      return 0
      ;;
  esac

  plist="$(solar_client_launchagent_plist_path)"
  plist_root=""
  if [[ -z "${SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE:-}" ]] \
    && solar_client_source_system_lib "$install_root"; then
    plist_root="$(solar_system_plist_solar_root "$plist" || true)"
  fi
  install_script="${SOLAR_CLIENT_LAUNCHAGENT_INSTALL_SCRIPT:-${install_root}/core/skills/solar-system/scripts/install_launchagent_macos.sh}"
  setup_script="${SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT:-${install_root}/core/skills/solar-gateway/scripts/setup_transport_gateway.sh}"

  echo "WARN: LaunchAgent SOLAR_ROOT is stale or incomplete (status=$status)"
  echo "  plist:  ${plist_root:-<missing>}"
  echo "  active: $install_root"
  echo "  (solar client update does not rewrite the LaunchAgent by default)"

  if [[ "$reinstall" == true ]]; then
    if [[ ! -f "$install_script" ]]; then
      echo "ERROR: missing $install_script" >&2
      return 1
    fi
    echo "Reinstalling LaunchAgent to embed current SOLAR_ROOT…"
    # Ensure child scripts resolve the post-update install.
    export SOLAR_ROOT="$install_root"
    [[ -n "${SOLAR_WORKSPACE:-}" ]] || export SOLAR_WORKSPACE="$(pwd)"
    bash "$install_script" || return 1
    if [[ -f "$setup_script" ]]; then
      echo "Restarting transport gateway so bridges inherit the new SOLAR_ROOT…"
      if ! bash "$setup_script" --restart; then
        echo "ERROR: LaunchAgent reinstalled but transport gateway restart failed" >&2
        echo "  bash \"$setup_script\" --restart" >&2
        return 1
      fi
    fi
    # Clear override so post-repair assess can reflect mocks / real state.
    if [[ -n "${SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE:-}" ]]; then
      # Test hook: after successful reinstall, treat binding as repaired.
      unset SOLAR_CLIENT_LAUNCHAGENT_STATUS_OVERRIDE
      echo "OK: LaunchAgent SOLAR_ROOT matches install"
      return 0
    fi
    status="$(solar_client_assess_launchagent "$install_root")"
    if [[ "$status" == "ok" ]]; then
      echo "OK: LaunchAgent SOLAR_ROOT matches install"
      return 0
    fi
    echo "ERROR: LaunchAgent still status=$status after reinstall — run: bash \"$install_root/core/skills/solar-system/scripts/check_orchestrator.sh\"" >&2
    return 1
  fi

  echo "  Fix:"
  echo "    solar client update --reinstall-launchagent"
  echo "  Or:"
  echo "    bash \"$install_script\""
  if [[ -f "$setup_script" ]]; then
    echo "    bash \"$setup_script\" --restart"
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
