#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"

STRICT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict) STRICT=true; shift ;;
    --check-plans|--check-git)
      echo "Use: solar workspace doctor $1" >&2
      exit 2
      ;;
    -h|--help)
      echo "Usage: solar client doctor [--strict]"
      echo "Workspace checks (sun/, planets/): solar workspace doctor [--check-plans] [--check-git]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1 (client doctor — use solar workspace doctor for sun/planets checks)" >&2
      exit 2
      ;;
  esac
done

solar_resolve_paths --quiet

warn_count=0
err_count=0

warn() { echo "WARN: $1"; warn_count=$((warn_count + 1)); }
err() { echo "ERROR: $1"; err_count=$((err_count + 1)); }
ok() { echo "OK: $1"; }

if [[ -d "$SOLAR_WORKSPACE/.solar/core" ]]; then
  err "obsolete .solar/core/ exists — run: solar client upgrade"
fi

if ! solar_client_paths_equal "$SOLAR_ROOT" "$SOLAR_WORKSPACE"; then
  artifact_count=0
  while IFS= read -r apath; do
    [[ -n "$apath" ]] || continue
    warn "install artifact under SOLAR_ROOT (not workspace): $apath — run: solar client upgrade"
    artifact_count=$((artifact_count + 1))
  done < <(solar_client_list_install_artifacts "$SOLAR_ROOT")
  if [[ "$artifact_count" -eq 0 ]]; then
    ok "SOLAR_ROOT has no IDE/agent prune artifacts"
  fi
else
  ok "SOLAR_ROOT equals SOLAR_WORKSPACE (no separate install prune needed)"
fi

if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SOLAR_WORKSPACE/.env"
  set +a
fi

MANIFEST="$SOLAR_WORKSPACE/.solar/manifest.json"
if [[ -f "$MANIFEST" ]]; then
  layout="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("layout",""))' "$MANIFEST" 2>/dev/null || true)"
  if [[ "$layout" == "solar-client-v1.1" ]]; then
    ok "manifest layout=$layout"
  elif [[ -n "$layout" ]]; then
    warn "manifest layout=$layout (expected solar-client-v1.1; run solar client upgrade)"
  else
    warn "manifest missing layout field (run solar client upgrade)"
  fi
  core_source="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("core_source",""))' "$MANIFEST" 2>/dev/null || true)"
  requires_global="$(solar_client_manifest_field "$MANIFEST" requires_global_client)"
  bundle_present=false
  [[ -d "$SOLAR_WORKSPACE/.solar/bundle" ]] && bundle_present=true

  if [[ "$core_source" == "global" ]]; then
    ok "manifest core_source=global (requires SOLAR_ROOT)"
    if [[ "$requires_global" == "false" ]]; then
      warn "manifest requires_global_client=false but core_source=global (drift)"
    fi
    if [[ "$bundle_present" == true ]]; then
      warn ".solar/bundle/ exists but manifest still global — run: solar client bundle create or remove bundle"
    fi
  elif [[ "$core_source" == "workspace-snapshot" ]]; then
    ok "manifest core_source=workspace-snapshot (portable)"
    if solar_client_bundle_validate "$SOLAR_WORKSPACE" true 2>/dev/null; then
      ok "workspace bundle valid"
    else
      err "workspace-snapshot bundle invalid — run: solar client bundle create"
    fi
    while IFS= read -r secret_hit; do
      [[ -n "$secret_hit" ]] || continue
      warn "bundle secret scan: $secret_hit"
    done < <(solar_client_bundle_scan_secrets "$SOLAR_WORKSPACE" 2>/dev/null || true)
    if solar_client_check_snapshot_outdated "$SOLAR_WORKSPACE" "$(solar_global_install_root 2>/dev/null || true)" 2>/dev/null; then
      warn "snapshot_outdated: global client newer than bundle — run: solar client bundle create"
    fi
    size_mb="$(solar_client_bundle_size_mb "$(solar_client_bundle_dir "$SOLAR_WORKSPACE")")"
    max_mb="$(solar_client_max_bundle_mb)"
    if python3 - <<PY "$size_mb" "$max_mb"
import sys
sys.exit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)
PY
    then
      ok "bundle size ${size_mb}MB (max ${max_mb}MB)"
    else
      warn "bundle size ${size_mb}MB exceeds max ${max_mb}MB"
      [[ "$STRICT" == true ]] && err "strict: bundle too large"
    fi
  elif [[ -n "$core_source" ]]; then
    warn "manifest core_source=$core_source (expected global or workspace-snapshot)"
  fi
  read -r global_ver global_commit < <(solar_client_git_identity "$SOLAR_ROOT" 2>/dev/null || echo "unknown unknown")
  manifest_ver="$(solar_client_manifest_core_version "$MANIFEST")"
  manifest_commit="$(solar_client_manifest_core_commit "$MANIFEST")"
  if [[ "$core_source" != "workspace-snapshot" ]]; then
  if [[ -n "$manifest_ver" && -n "$global_ver" && "$manifest_ver" != "$global_ver" && "$global_ver" != dev* && "$global_ver" != unknown ]]; then
    warn "manifest core_version=$manifest_ver but global client is $global_ver — run: solar client sync"
    if [[ "$STRICT" == true ]]; then
      err "strict: workspace manifest out of sync with SOLAR_ROOT after global update"
    fi
  elif [[ -n "$manifest_ver" ]]; then
    ok "manifest core_version=$manifest_ver matches global client"
  fi
  if [[ -n "$global_commit" && "$global_commit" != unknown && -n "$manifest_commit" && "$manifest_commit" != "$global_commit" ]]; then
    warn "manifest core_commit=${manifest_commit:0:12} but SOLAR_ROOT HEAD is ${global_commit:0:12} — run: solar client sync"
    [[ "$STRICT" == true ]] && err "strict: manifest core_commit out of sync with SOLAR_ROOT"
  elif [[ -n "$manifest_commit" && -n "$global_commit" && "$global_commit" != unknown ]]; then
    ok "manifest core_commit matches SOLAR_ROOT HEAD"
  fi
  fi
  if solar_client_manifest_needs_repair "$MANIFEST"; then
    warn "manifest needs repair (invalid JSON, merge markers, or missing fields) — run: solar client update --repair"
    [[ "$STRICT" == true ]] && err "strict: manifest repair required"
  fi
else
  warn ".solar/manifest.json missing (run solar client init or upgrade)"
fi

if [[ "$(solar_core_dir)" == "$SOLAR_WORKSPACE/.solar/core" ]]; then
  err "install root must not be workspace .solar/core/ (run solar client upgrade)"
fi

for f in CLAUDE.md GEMINI.md .cursorrules; do
  if [[ -L "$SOLAR_WORKSPACE/$f" ]]; then
    ok "$f -> $(readlink "$SOLAR_WORKSPACE/$f")"
  elif [[ -f "$SOLAR_WORKSPACE/$f" ]] && grep -q "symlink unavailable" "$SOLAR_WORKSPACE/$f" 2>/dev/null; then
    warn "$f is a stub (symlink failed; OneDrive/Windows?)"
  elif [[ -f "$SOLAR_WORKSPACE/$f" ]]; then
    warn "$f is a regular file, not a symlink to AGENTS.md"
  fi
done

if command -v git >/dev/null 2>&1 && git -C "$SOLAR_WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git -C "$SOLAR_WORKSPACE" ls-files --error-unmatch .env >/dev/null 2>&1; then
    err ".env is tracked by git in SOLAR_WORKSPACE (secrets risk — untrack .env)"
  else
    ok ".env not tracked by git"
  fi
fi

SOLAR_CLIENT_SCRIPT_DIR="$SCRIPT_DIR"
# shellcheck source=client_doctor_lib.sh
source "$SCRIPT_DIR/client_doctor_lib.sh"

_port_check_verbose() {
  local var="$1"
  local port="${!var:-}"
  [[ -n "$port" ]] || return 0

  local pid
  pid="$(_solar_client_port_listener_pid "$port" || true)"
  [[ -n "$pid" ]] || return 0

  case "$var" in
    SOLAR_INTERFACE_PORT)
      if _solar_client_is_interface_port "$port" "$pid"; then
        ok "$var=$port in use by solar-interface (pid $pid)"
        return 0
      fi
      ;;
    SOLAR_HTTP_PORT)
      if _solar_client_is_http_port "$port" "$pid"; then
        ok "$var=$port in use by solar-gateway (pid $pid)"
        return 0
      fi
      ;;
  esac

  warn "$var=$port is in use by a non-Solar process (pid $pid); override in .env if another workspace"
}

_port_check_verbose SOLAR_INTERFACE_PORT
_port_check_verbose SOLAR_HTTP_PORT

echo "Summary: $err_count error(s), $warn_count warning(s)"
[[ "$err_count" -eq 0 ]]
