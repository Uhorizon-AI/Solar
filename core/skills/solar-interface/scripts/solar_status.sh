#!/usr/bin/env bash
# solar_status.sh — compact workspace health (Client + Workspace + runtime).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-client/scripts" && pwd)"
# shellcheck source=resolve_solar_paths.sh
source "$SCRIPT_DIR/resolve_solar_paths.sh"
# shellcheck source=client_lib.sh
source "$CLIENT_SCRIPTS/client_lib.sh"
solar_resolve_paths --quiet

VERBOSE=false
JSON=false
STRICT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verbose) VERBOSE=true; shift ;;
    --json) JSON=true; shift ;;
    --strict) STRICT=true; shift ;;
    -h|--help)
      echo "Usage: solar status [--verbose] [--json] [--strict]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

block_line() {
  local name="$1"
  local state="$2"
  local detail="${3:-}"
  if [[ "$JSON" == true ]]; then
    return 0
  fi
  printf "%-10s %s" "$name:" "$state"
  [[ -n "$detail" ]] && printf "  (%s)" "$detail"
  echo
}

host_state="DOWN"
host_detail=""
workspace_state="FAIL"
system_state="INFO"
router_state="INFO"
router_detail=""
browser_state="INFO"
client_state="OK"
client_detail=""
mcp_info=""

# host (Solar App :9000 in-process) — fallback to legacy interface daemon for dev
HOST_SCRIPTS="$(solar_core_dir)/skills/solar-host/scripts"
if [[ -f "$HOST_SCRIPTS/check_host.sh" ]]; then
  # shellcheck source=/dev/null
  source "$HOST_SCRIPTS/host_lib.sh"
  solar_host_load_env
  if bash "$HOST_SCRIPTS/check_host.sh" --quiet 2>/dev/null; then
    host_state="OK"
    host_detail="$SOLAR_HOST_BASE_URL"
    if command -v curl >/dev/null 2>&1; then
      runtime_json="$(curl -fsS --max-time 3 "$SOLAR_HOST_BASE_URL/api/runtime/health" 2>/dev/null || true)"
      if [[ -n "$runtime_json" ]] && echo "$runtime_json" | grep -q '"status"[[:space:]]*:[[:space:]]*"not_ready"'; then
        host_state="WARN"
        host_detail="$SOLAR_HOST_BASE_URL in-process not ready"
      fi
    fi
  elif bash "$SCRIPT_DIR/check_interface.sh" --quiet 2>/dev/null; then
    host_state="OK"
    host_detail="legacy daemon ${SOLAR_INTERFACE_BASE_URL:-:7741}"
  fi
elif bash "$SCRIPT_DIR/check_interface.sh" --quiet 2>/dev/null; then
  host_state="OK"
  host_detail="legacy daemon"
fi

# workspace content (sun/ + planets/)
workspace_detail=""
if [[ -f "$SOLAR_WORKSPACE/sun/preferences/profile.md" && -f "$SOLAR_WORKSPACE/sun/MEMORY.md" ]]; then
  workspace_state="OK"
else
  workspace_state="WARN"
  workspace_detail="missing profile.md or MEMORY.md"
fi
if [[ ! -d "$SOLAR_WORKSPACE/planets" ]]; then
  workspace_state="WARN"
  workspace_detail="${workspace_detail:+$workspace_detail; }planets/ missing"
fi

# system (LaunchAgent) — capture output first: status_launchagent may exit 1
# after printing launchctl_loaded (e.g. stderr log awk) which breaks pipefail in "cmd | grep".
if [[ -f "$(solar_core_dir)/skills/solar-system/scripts/status_launchagent_macos.sh" ]]; then
  system_out="$(bash "$(solar_core_dir)/skills/solar-system/scripts/status_launchagent_macos.sh" 2>/dev/null || true)"
  if echo "$system_out" | grep -q "launchctl_loaded: true"; then
    system_state="OK"
  elif echo "$system_out" | grep -q "launchctl_loaded: false"; then
    system_state="WARN"
  else
    system_state="WARN"
  fi
elif [[ -f "$(solar_core_dir)/skills/solar-system/scripts/check_orchestrator.sh" ]]; then
  orch_out="$(bash "$(solar_core_dir)/skills/solar-system/scripts/check_orchestrator.sh" 2>/dev/null || true)"
  if echo "$orch_out" | grep -q "Verdict: HEALTHY"; then
    system_state="OK"
  elif echo "$orch_out" | grep -q "Verdict: PARTIAL"; then
    system_state="WARN"
  else
    system_state="WARN"
  fi
else
  system_state="INFO"
fi

# router — WARN only for recent orphans (default last 24h); historical noise ignored
if [[ -f "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" ]]; then
  stale_n=0
  stale_n="$(bash "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" --stale-count 2>/dev/null || echo 0)"
  stale_all=0
  stale_all="$(bash "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" --stale-count-all 2>/dev/null || echo 0)"
  if [[ "${stale_n:-0}" -gt 0 ]]; then
    router_state="WARN"
    router_detail="${stale_n} stale in-flight (<24h)"
  elif [[ "${stale_all:-0}" -gt 0 ]]; then
    router_state="OK"
    router_detail="${stale_all} historical orphan(s); run reconcile_router_audit.sh"
  else
    router_state="OK"
  fi
else
  router_state="INFO"
fi

# browser (on-demand; INFO by default per plan)
if [[ -f "$(solar_core_dir)/skills/solar-browser/scripts/check_browser.sh" ]]; then
  if bash "$(solar_core_dir)/skills/solar-browser/scripts/check_browser.sh" 2>/dev/null | grep -qi "running\|ok\|healthy"; then
    browser_state="OK"
  else
    browser_state="INFO"
  fi
fi

# workspace client checks (symlinks, foreign port listeners) — criteria #6/#17
if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SOLAR_WORKSPACE/.env"
  set +a
fi
SOLAR_CLIENT_SCRIPT_DIR="$CLIENT_SCRIPTS"
# shellcheck source=client_doctor_lib.sh
source "$CLIENT_SCRIPTS/client_doctor_lib.sh"
if ! solar_client_check_governance_symlinks; then
  client_state="WARN"
  client_detail="${SOLAR_CLIENT_GOV_MSG}"
fi
if ! solar_client_check_ports; then
  client_state="WARN"
  if [[ -n "$client_detail" ]]; then
    client_detail="$client_detail; ${SOLAR_CLIENT_PORTS_MSG}"
  else
    client_detail="${SOLAR_CLIENT_PORTS_MSG}"
  fi
fi

MANIFEST="$SOLAR_WORKSPACE/.solar/manifest.json"
if [[ -f "$MANIFEST" ]]; then
  _core_src="$(solar_client_manifest_core_source "$MANIFEST")"
  if [[ "$_core_src" == "workspace-snapshot" ]]; then
    _core_line="core_source=workspace-snapshot (portable)"
    if solar_client_check_snapshot_outdated "$SOLAR_WORKSPACE" "$(solar_global_install_root 2>/dev/null || true)" 2>/dev/null; then
      _core_line="$_core_line snapshot_outdated"
      [[ "$client_state" == "OK" ]] && client_state="WARN"
    fi
  else
    _core_line="core_source=global (requires SOLAR_ROOT)"
  fi
  if [[ -n "$client_detail" ]]; then
    client_detail="$client_detail; $_core_line"
  else
    client_detail="$_core_line"
  fi
fi

if [[ "$JSON" == true ]]; then
  python3 - <<PY
import json
print(json.dumps({
  "SOLAR_WORKSPACE": "$SOLAR_WORKSPACE",
  "SOLAR_ROOT": "$SOLAR_ROOT",
  "host": "$host_state",
  "host_detail": "$host_detail",
  "workspace": "$workspace_state",
  "workspace_detail": "$workspace_detail",
  "system": "$system_state",
  "router": "$router_state",
  "router_detail": "$router_detail",
  "browser": "$browser_state",
  "client": "$client_state",
  "client_detail": "$client_detail",
}, indent=2))
PY
  exit 0
fi

echo "Solar status  SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
block_line "host" "$host_state" "$host_detail"
block_line "client" "$client_state" "$client_detail"
block_line "workspace" "$workspace_state" "$workspace_detail"
block_line "system" "$system_state"
block_line "router" "$router_state" "$router_detail"
block_line "browser" "$browser_state"

if [[ "$host_state" == "WARN" ]]; then
  echo "hint: curl \$SOLAR_HOST_BASE_URL/api/runtime/health"
fi
if [[ -n "$router_detail" ]] && echo "$router_detail" | grep -q "historical orphan"; then
  echo "hint: bash core/skills/solar-router/scripts/reconcile_router_audit.sh --dry-run"
fi
if [[ "$client_state" == "WARN" ]]; then
  echo "hint: solar client doctor"
fi
if [[ "$workspace_state" == "WARN" ]]; then
  echo "hint: solar workspace doctor"
fi

if [[ "$VERBOSE" == true ]]; then
  echo "---"
  if [[ -f "$HOST_SCRIPTS/check_host.sh" ]]; then
    bash "$HOST_SCRIPTS/check_host.sh" 2>/dev/null || true
  else
    bash "$SCRIPT_DIR/status_interface.sh" 2>/dev/null || true
  fi
  if [[ -f "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" ]]; then
    bash "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" 2>/dev/null | head -20 || true
    [[ -n "$router_detail" ]] && echo "router stale: $router_detail"
  fi
  if [[ -f "$SOLAR_WORKSPACE/.cursor/mcp.json" ]]; then
    echo "mcp: $SOLAR_WORKSPACE/.cursor/mcp.json (configure servers in Cursor Settings)"
  else
    echo "mcp: INFO no .cursor/mcp.json in workspace"
  fi
fi

fail=0
for s in "$host_state" "$workspace_state"; do
  [[ "$s" == "FAIL" ]] && fail=1
done
if [[ "$STRICT" == true ]]; then
  for s in "$host_state" "$workspace_state" "$client_state" "$system_state" "$router_state"; do
    [[ "$s" == "FAIL" || "$s" == "WARN" ]] && fail=1
  done
fi
exit "$fail"
