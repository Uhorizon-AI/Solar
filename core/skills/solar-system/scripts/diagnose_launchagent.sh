#!/usr/bin/env bash
# One-pass diagnostic for LaunchAgent bootstrap error 5.
# Usage: run from repo root: bash core/skills/solar-system/scripts/diagnose_launchagent.sh
set -euo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
cd "$REPO_ROOT"

ENTRYPOINT="$REPO_ROOT/core/skills/solar-system/scripts/Solar"
ORCHESTRATOR="$REPO_ROOT/core/skills/solar-system/scripts/run_orchestrator.sh"
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
echo "=== 5. Plist lint ==="
tmp_plist=$(mktemp)
trap 'rm -f "$tmp_plist"' EXIT
bash core/skills/solar-system/scripts/render_launchagent_plist.sh "$tmp_plist" >/dev/null
plutil -lint "$tmp_plist" && echo "OK: plist valid"

echo ""
echo "=== 6. Current job state ==="
launchctl print "$DOMAIN/$LABEL" 2>/dev/null | head -5 || echo "Job not loaded (expected if bootstrap fails)"

echo ""
echo "=== 7. Run entrypoint manually (sanity) ==="
"$ENTRYPOINT" 2>&1 | head -3 && echo "OK: runs" || true
