#!/usr/bin/env bash
# solar_status.sh — compact workspace health (5 blocks).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_paths.sh
source "$SCRIPT_DIR/resolve_solar_paths.sh"
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

iface_state="FAIL"
sun_state="FAIL"
system_state="INFO"
router_state="INFO"
browser_state="INFO"
client_state="OK"
client_detail=""

# interface
if bash "$SCRIPT_DIR/check_interface.sh" --quiet 2>/dev/null; then
  iface_state="OK"
else
  iface_state="DOWN"
fi

# sun (profile + memory)
if [[ -f "$SOLAR_WORKSPACE/sun/preferences/profile.md" && -f "$SOLAR_WORKSPACE/sun/MEMORY.md" ]]; then
  sun_state="OK"
else
  sun_state="WARN"
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

# router
if [[ -f "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" ]]; then
  router_out="$(bash "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" 2>/dev/null | head -5 || true)"
  if echo "$router_out" | grep -qi "stale\|warn"; then
    router_state="WARN"
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
SOLAR_CLIENT_SCRIPT_DIR="$SCRIPT_DIR"
# shellcheck source=client_doctor_lib.sh
source "$SCRIPT_DIR/client_doctor_lib.sh"
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

if [[ "$JSON" == true ]]; then
  python3 - <<PY
import json
print(json.dumps({
  "SOLAR_WORKSPACE": "$SOLAR_WORKSPACE",
  "SOLAR_ROOT": "$SOLAR_ROOT",
  "interface": "$iface_state",
  "sun": "$sun_state",
  "system": "$system_state",
  "router": "$router_state",
  "browser": "$browser_state",
  "client": "$client_state",
  "client_detail": "$client_detail",
}, indent=2))
PY
  exit 0
fi

echo "Solar status  SOLAR_WORKSPACE=$SOLAR_WORKSPACE"
block_line "interface" "$iface_state"
block_line "sun" "$sun_state"
block_line "system" "$system_state"
block_line "router" "$router_state"
block_line "browser" "$browser_state"
block_line "client" "$client_state" "$client_detail"

if [[ "$VERBOSE" == true ]]; then
  echo "---"
  bash "$SCRIPT_DIR/status_interface.sh" 2>/dev/null || true
  if [[ -f "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" ]]; then
    bash "$(solar_core_dir)/skills/solar-router/scripts/status_router.sh" 2>/dev/null | head -20 || true
  fi
fi

fail=0
for s in "$iface_state" "$sun_state"; do
  [[ "$s" == "FAIL" ]] && fail=1
done
if [[ "$STRICT" == true ]]; then
  for s in "$iface_state" "$sun_state" "$system_state" "$router_state"; do
    [[ "$s" == "FAIL" || "$s" == "WARN" ]] && fail=1
  done
fi
exit "$fail"
