#!/usr/bin/env bash
# Consolidated read-only view of work in flight: canonical intention, machine
# queue, today's blockers, A3 mandates. On demand only — no cadence, no push,
# no generated artifact. For workspace health use `solar status` instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../solar-client/scripts/resolve_solar_paths.sh
source "$SCRIPT_DIR/../../solar-client/scripts/resolve_solar_paths.sh"
solar_resolve_paths --quiet
cd "$SOLAR_WORKSPACE"

echo "## Continuity"
if [[ -f sun/runtime/continuity/active.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("sun/runtime/continuity/active.json").read_text(encoding="utf-8"))
fields = [
    ("intention_id", "(none)"),
    ("active_task", "(none)"),
    ("next_owner", "(unset)"),
    ("updated_at", "(unknown)"),
]
for key, fallback in fields:
    print(f"- {key}: {data.get(key) or fallback}")
for key in ("pending", "constraints", "channels_seen"):
    values = data.get(key) or []
    print(f"- {key}: {'; '.join(values) if values else '(none)'}")
PY
else
  echo "- (no active.json yet)"
fi

echo
echo "## Async tasks (machine)"
for state in drafts planned queued active error; do
  dir="sun/runtime/async-tasks/$state"
  if [[ -d "$dir" ]]; then
    count=$(find "$dir" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')
    echo "- $state: $count"
  fi
done

echo
echo "## Blockers today"
TODAY="$(date +%Y-%m-%d)"
DAILY_LOG="sun/daily-log/${TODAY}.md"
if [[ -f "$DAILY_LOG" ]]; then
  awk '/^## Blockers/,/^##/{if(/^## / && !/^## Blockers/) exit; print}' "$DAILY_LOG" | sed '1d' | head -20
else
  echo "- (no daily-log for $TODAY)"
fi

echo
echo "## A3 mandates"
if [[ -d sun/delegations ]]; then
  python3 "$SCRIPT_DIR/delegation_ctl.py" status
else
  echo "- (no sun/delegations yet)"
fi
