#!/usr/bin/env bash
# check_async_tasks.sh — Check whether solar-system is supervising async-tasks.
#
# Exit codes:
#   0 — solar-system is active and supervising async-tasks (no action needed)
#   1 — solar-system is not supervising async-tasks (caller should run fallback)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

log() { $QUIET || echo "$*"; }

# 1. Check if the Solar system supervisor is installed
PLIST_PATH="$HOME/Library/LaunchAgents/com.solar.system.plist"
if [[ ! -f "$PLIST_PATH" ]]; then
  log "⏸️  solar-system supervisor not installed for async-tasks."
  exit 1
fi

# 2. Check if the supervisor is active in launchctl
if ! launchctl list 2>/dev/null | grep -q "com.solar.system"; then
  log "⏸️  solar-system supervisor is installed but not active."
  exit 1
fi

# 3. Check if async-tasks is delegated to solar-system in .env
ENV_FILE="$REPO_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  log "⏸️  .env not found, cannot verify async-tasks supervision."
  exit 1
fi

FEATURES="$(grep -E '^SOLAR_SYSTEM_FEATURES=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)"
if [[ -z "$FEATURES" ]] || ! echo ",$FEATURES," | grep -q ",async-tasks,"; then
  log "⏸️  solar-system is active but not configured to supervise async-tasks."
  exit 1
fi

log "✅ solar-system is supervising async-tasks."
exit 0
