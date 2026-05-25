#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=client_lib.sh
source "$SCRIPT_DIR/client_lib.sh"
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
  core_source="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("core_source",""))' "$MANIFEST" 2>/dev/null || true)"
  if [[ "$layout" == "solar-client-v1.1" ]]; then
    ok "manifest layout=$layout"
  elif [[ -n "$layout" ]]; then
    warn "manifest layout=$layout (expected solar-client-v1.1; run solar client upgrade)"
  else
    warn "manifest missing layout field (run solar client upgrade)"
  fi
  if [[ "$core_source" == "global" ]]; then
    ok "manifest core_source=global"
  elif [[ -n "$core_source" ]]; then
    warn "manifest core_source=$core_source (expected global)"
  fi
  global_ver="$(solar_client_git_identity "$SOLAR_ROOT" | awk '{print $1}')"
  manifest_ver="$(solar_client_manifest_core_version "$MANIFEST")"
  if [[ -n "$manifest_ver" && -n "$global_ver" && "$manifest_ver" != "$global_ver" && "$global_ver" != dev* ]]; then
    warn "manifest core_version=$manifest_ver but global client is $global_ver (run solar client sync)"
  elif [[ -n "$manifest_ver" ]]; then
    ok "manifest core_version=$manifest_ver matches global client"
  fi
else
  warn ".solar/manifest.json missing (run solar client init or upgrade)"
fi

if [[ "$(solar_core_dir)" == "$SOLAR_WORKSPACE/.solar/core" ]]; then
  err "install root must not be workspace .solar/core/ (run solar client upgrade)"
fi

if [[ -f "$(solar_core_dir)/scripts/sun-workspace-doctor.sh" ]]; then
  bash "$(solar_core_dir)/scripts/sun-workspace-doctor.sh" "$@" || err_count=$((err_count + 1))
else
  err "sun-workspace-doctor.sh not found under SOLAR_ROOT=$SOLAR_ROOT"
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
        ok "$var=$port in use by solar-transport-gateway (pid $pid)"
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
