#!/usr/bin/env bash
# status_router.sh — Solar Router live status
# Shows: provider health, in-flight processes, last executions
# Usage: bash core/skills/solar-router/scripts/status_router.sh [--last N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$RESOLVE_SCRIPT"
solar_resolve_paths --quiet
SOLAR_WORKSPACE="${SOLAR_WORKSPACE:-$SOLAR_WORKSPACE}"
# shellcheck source=/dev/null
source "$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/solar_runtime_paths.sh"
STATE_SCRIPTS="$(cd "$SCRIPT_DIR/../../solar-state/scripts" && pwd)"
export STATE_SCRIPTS
PYTHON="${SOLAR_AI_ROUTER_PYTHON:-python3}"
LAST_N=10

STALE_COUNT_ONLY=false
STALE_ALL=false
STALE_MAX_AGE_HOURS="${SOLAR_ROUTER_STALE_WARN_MAX_AGE_HOURS:-24}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --last) shift; LAST_N="${1:-10}"; shift ;;
    --stale-count) STALE_COUNT_ONLY=true; shift ;;
    --stale-count-all) STALE_COUNT_ONLY=true; STALE_ALL=true; shift ;;
    --max-age-hours)
      shift
      STALE_MAX_AGE_HOURS="${1:-24}"
      shift
      ;;
    *) shift ;;
  esac
done

if [[ "$STALE_COUNT_ONLY" == true ]]; then
  export STALE_ALL STALE_MAX_AGE_HOURS
  $PYTHON - <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, os.environ["STATE_SCRIPTS"])
import solar_state

count_all = os.environ.get("STALE_ALL", "false").lower() == "true"
max_age_h = float(os.environ.get("STALE_MAX_AGE_HOURS", "24"))

starts = {}
ends = set()
try:
    with solar_state.session() as store:
        loaded = store.audit_rows()
except solar_state.StateError:
    print("0")
    raise SystemExit(0)
for row in loaded:
    rid = row.get("router_id", "")
    if row.get("event") == "start":
        starts[rid] = row
    elif row.get("event") == "end":
        ends.add(rid)

now = datetime.now(timezone.utc)
stale = 0
for rid, row in starts.items():
    if rid in ends:
        continue
    if count_all:
        stale += 1
        continue
    ts_raw = row.get("ts", "")
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        continue
    age_h = (now - ts).total_seconds() / 3600.0
    if age_h <= max_age_h:
        stale += 1
print(stale)
PYEOF
  exit 0
fi

echo ""
echo "══════════════════════════════════════════════"
echo "  Solar Router — Status"
echo "══════════════════════════════════════════════"

# ---------------------------------------------------------------------------
# 1. Provider health (dry-run)
# ---------------------------------------------------------------------------
echo ""
echo "  Providers:"
bash "$SCRIPT_DIR/diagnose_router.sh" --dry-run 2>/dev/null \
  | grep -E "^\s+- (codex|claude|agy)" \
  | sed 's/^/  /' \
  || echo "    (diagnose_router.sh not available)"

# ---------------------------------------------------------------------------
# 2. In-flight processes (start without matching end)
# ---------------------------------------------------------------------------
echo ""
echo "  In-flight:"

$PYTHON - <<'PYEOF'
import os, sys, datetime
sys.path.insert(0, os.environ["STATE_SCRIPTS"])
import solar_state

starts = {}
ends = set()
try:
    with solar_state.session() as store:
        loaded = store.audit_rows()
except solar_state.StateError:
    print("    (no audit yet)")
    raise SystemExit(0)
for row in loaded:
    rid = row.get("router_id", "")
    if row.get("event") == "start":
        starts[rid] = row
    elif row.get("event") == "end":
        ends.add(rid)

in_flight = {rid: row for rid, row in starts.items() if rid not in ends}

if not in_flight:
    print("    (none)")
else:
    now = datetime.datetime.utcnow()
    for rid, row in in_flight.items():
        ts_str = row.get("ts", "")
        try:
            ts = datetime.datetime.fromisoformat(ts_str.rstrip("Z"))
            elapsed = int((now - ts).total_seconds())
            elapsed_str = f"{elapsed}s ago"
        except Exception:
            elapsed_str = "unknown"
        req_id = row.get("request_id", "")
        user = row.get("user_id", "")
        print(f"    - router_id={rid[:8]}...  request_id={req_id}  user={user}  started {elapsed_str}")
PYEOF

# ---------------------------------------------------------------------------
# 3. Last N executions
# ---------------------------------------------------------------------------
echo ""
echo "  Last $LAST_N executions:"

$PYTHON - "$LAST_N" <<'PYEOF'
import os, sys
sys.path.insert(0, os.environ["STATE_SCRIPTS"])
import solar_state

last_n = int(sys.argv[1])
starts = {}
ends = {}
try:
    with solar_state.session() as store:
        loaded = store.audit_rows()
except solar_state.StateError:
    print("    (no audit yet)")
    raise SystemExit(0)
for row in loaded:
    rid = row.get("router_id", "")
    if row.get("event") == "start":
        starts[rid] = row
    elif row.get("event") == "end":
        ends[rid] = row

# Merge start+end, sorted by start ts descending
merged = []
for rid, start in starts.items():
    end = ends.get(rid)
    merged.append((start.get("ts", ""), rid, start, end))

merged.sort(key=lambda x: x[0], reverse=True)

if not merged:
    print("    (no executions yet)")
else:
    for ts, rid, start, end in merged[:last_n]:
        time_str = ts[11:16] if len(ts) >= 16 else ts
        user = start.get("user_id", "-")
        req_id = start.get("request_id", "-")
        meta = start.get("metadata") or {}
        agent = meta.get("agent") or "-"
        planet = meta.get("planet") or "-"

        if end:
            status = end.get("status", "-")
            provider = end.get("provider") or "-"
            duration = end.get("duration_ms")
            jit = end.get("jit_generated", False)
            duration_str = f"{duration}ms" if duration is not None else "-"
            jit_str = "jit=yes" if jit else "jit=no"
            print(f"    - {time_str}  router={rid[:8]}  req={req_id[:12]}  user={user}  {provider}  {status}  {duration_str}  {jit_str}  agent={agent}  planet={planet}")
        else:
            print(f"    - {time_str}  router={rid[:8]}  req={req_id[:12]}  user={user}  (in-flight)  agent={agent}  planet={planet}")
PYEOF

echo ""
echo "══════════════════════════════════════════════"
echo ""
