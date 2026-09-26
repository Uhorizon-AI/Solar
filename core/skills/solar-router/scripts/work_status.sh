#!/usr/bin/env bash
# Consolidated read-only view of work in flight: canonical intention, machine
# queue, today's blockers, A3 mandates. On demand only — no cadence, no push,
# no generated artifact. For workspace health use `solar status` instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../solar-paths/scripts/resolve_solar_paths.sh
source "$SCRIPT_DIR/../../solar-paths/scripts/resolve_solar_paths.sh"
solar_resolve_paths --quiet
# shellcheck source=../../solar-paths/scripts/solar_runtime_paths.sh
source "$SCRIPT_DIR/../../solar-paths/scripts/solar_runtime_paths.sh"
cd "$SOLAR_WORKSPACE"

echo "## Continuity"
STATE_PY="$(cd "$SCRIPT_DIR/../../solar-state/scripts" && pwd)/solar_state.py"
if continuity="$(python3 "$STATE_PY" continuity get 2>/dev/null)" && [[ "$continuity" != "null" ]]; then
  CONTINUITY_JSON="$continuity" python3 - <<'PY'
import json, os
data = json.loads(os.environ["CONTINUITY_JSON"]) or {}
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
    shown = "; ".join(str(value) for value in values) if values else "(none)"
    print(f"- {key}: {shown}")
PY
else
  echo "- (no continuity record yet)"
fi

echo
echo "## Async tasks (machine)"
STATE_PY="$(cd "$SCRIPT_DIR/../../solar-state/scripts" && pwd)/solar_state.py"
if counts="$(python3 "$STATE_PY" task counts 2>/dev/null)"; then
  printf '%s' "$counts" | python3 -c 'import json,sys
data=json.load(sys.stdin)
labels=("draft","planned","queued","active","error","completed","cancelled","archived")
names={"draft":"drafts","archived":"archive"}
for key in labels:
    print(f"- {names.get(key, key)}: {data.get(key, 0)}")'
else
  echo "- (task queue is not sqlite yet)"
fi

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
python3 "$SCRIPT_DIR/delegation_ctl.py" status
