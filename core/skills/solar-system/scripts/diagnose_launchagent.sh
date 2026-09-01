#!/usr/bin/env bash
# One-pass diagnostic for LaunchAgent bootstrap error 5.
# Usage: run from repo root: bash core/skills/solar-system/scripts/diagnose_launchagent.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=system_lib.sh
source "$SCRIPT_DIR/system_lib.sh"

if [[ -n "${1:-}" ]]; then
  SOLAR_WORKSPACE="$1"
else
  solar_system_bind_workspace
  SOLAR_WORKSPACE="$SOLAR_WORKSPACE"
fi
cd "$SOLAR_WORKSPACE"
solar_system_load_env

ENTRYPOINT="$(solar_system_entrypoint "$SOLAR_WORKSPACE")"
ORCHESTRATOR="$(solar_system_orchestrator_script "$SOLAR_WORKSPACE")"
STDOUT="${SOLAR_SYSTEM_STDOUT_PATH:-$HOME/Library/Logs/com.solar.system/stdout.log}"
STDERR="${SOLAR_SYSTEM_STDERR_PATH:-$HOME/Library/Logs/com.solar.system/stderr.log}"
LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
DOMAIN="gui/$(id -u)"

echo "=== 1. Entrypoint exists and is executable ==="
ls -la "$ENTRYPOINT" 2>/dev/null || { echo "MISSING: $ENTRYPOINT"; exit 1; }
[[ -x "$ENTRYPOINT" ]] && echo "OK: executable" || echo "FAIL: not executable (chmod +x)"

echo ""
echo "=== 2. run_orchestrator.sh exists and is executable ==="
ls -la "$ORCHESTRATOR" 2>/dev/null || { echo "MISSING: $ORCHESTRATOR"; exit 1; }
[[ -x "$ORCHESTRATOR" ]] && echo "OK: executable" || echo "FAIL: not executable (chmod +x)"

echo ""
echo "=== 3. Line endings (CRLF can cause EIO) ==="
file "$ENTRYPOINT" "$ORCHESTRATOR"
od -c "$ENTRYPOINT" | head -1

echo ""
echo "=== 4. Log paths writable ==="
touch "$STDOUT" "$STDERR" 2>/dev/null && echo "OK: $STDOUT $STDERR" || echo "FAIL: cannot create log files"

echo ""
echo "=== 5. Plist lint + SOLAR_ROOT binding ==="
tmp_plist=$(mktemp)
trap 'rm -f "$tmp_plist"' EXIT
bash "$SOLAR_ROOT/core/skills/solar-system/scripts/render_launchagent_plist.sh" "$tmp_plist" >/dev/null
plutil -lint "$tmp_plist" && echo "OK: rendered plist valid"

INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
if [[ -f "$INSTALLED_PLIST" ]]; then
  plist_root="$(solar_system_plist_solar_root "$INSTALLED_PLIST" || true)"
  plist_status="$(solar_system_classify_plist_root "$plist_root" "$SOLAR_ROOT")"
  echo "Installed plist: $INSTALLED_PLIST"
  echo "  plist_SOLAR_ROOT: ${plist_root:-<missing>}"
  echo "  active_SOLAR_ROOT: $SOLAR_ROOT"
  echo "  plist_root_status: $plist_status"
  case "$plist_status" in
    ok) echo "OK: LaunchAgent SOLAR_ROOT matches active install" ;;
    *)
      echo "FAIL: plist_root_status=$plist_status — reinstall LaunchAgent:"
      echo "  bash \"$SOLAR_ROOT/core/skills/solar-system/scripts/install_launchagent_macos.sh\""
      ;;
  esac
else
  echo "Installed plist: missing ($INSTALLED_PLIST)"
fi

echo ""
echo "=== 6. Current job state ==="
launchctl print "$DOMAIN/$LABEL" 2>/dev/null | head -5 || echo "Job not loaded (expected if bootstrap fails)"

echo ""
echo "=== 7. Run entrypoint manually (sanity) ==="
(cd "$SOLAR_WORKSPACE" && "$ENTRYPOINT") 2>&1 | head -3 && echo "OK: runs" || true
