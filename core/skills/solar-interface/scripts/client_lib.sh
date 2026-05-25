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
