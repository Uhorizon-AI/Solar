#!/usr/bin/env bash
# reconcile_router_audit.sh — close orphan router audit starts (append synthetic end events).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$RESOLVE_SCRIPT"
solar_resolve_paths --quiet

# shellcheck source=/dev/null
source "$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/solar_runtime_paths.sh"
STATE_PY="$(cd "$SCRIPT_DIR/../../solar-state/scripts" && pwd)/solar_state.py"
MIN_AGE_HOURS="${SOLAR_ROUTER_RECONCILE_MIN_AGE_HOURS:-1}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --min-age-hours)
      shift
      MIN_AGE_HOURS="${1:-1}"
      shift
      ;;
    -h|--help)
      echo "Usage: reconcile_router_audit.sh [--dry-run] [--min-age-hours N]"
      echo "  Appends end events for start records without a matching end (orphans)."
      echo "  Default min age: \${SOLAR_ROUTER_RECONCILE_MIN_AGE_HOURS:-1} hour(s)."
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

export MIN_AGE_HOURS DRY_RUN STATE_PY
python3 - <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["STATE_PY"]).parent))
import solar_state

min_age_hours = float(os.environ.get("MIN_AGE_HOURS", "1"))
dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

starts: dict[str, dict] = {}
ends: set[str] = set()
try:
    with solar_state.session() as store:
        loaded = store.audit_rows()
except solar_state.StateError as exc:
    print(f"OK: audit is not sqlite yet ({exc})")
    sys.exit(0)
for row in loaded:
    rid = row.get("router_id", "")
    if not rid:
        continue
    if row.get("event") == "start":
        starts[rid] = row
    elif row.get("event") == "end":
        ends.add(rid)

now = datetime.now(timezone.utc)
orphans: list[tuple[str, dict]] = []

for rid, row in starts.items():
    if rid in ends:
        continue
    ts_raw = row.get("ts", "")
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        orphans.append((rid, row))
        continue
    age_h = (now - ts).total_seconds() / 3600.0
    if age_h >= min_age_hours:
        orphans.append((rid, row))

if not orphans:
    print("OK: no orphan audit records to reconcile")
    sys.exit(0)

print(f"{'DRY-RUN: would reconcile' if dry_run else 'Reconciling'} {len(orphans)} orphan record(s) (min_age={min_age_hours}h)")

if dry_run:
    for rid, row in orphans[:5]:
        print(f"  - {rid[:8]}... started {row.get('ts', '?')}")
    if len(orphans) > 5:
        print(f"  ... and {len(orphans) - 5} more")
    sys.exit(0)

for rid, row in orphans:
    ts_raw = row.get("ts", "")
    duration_ms = 0
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        duration_ms = max(0, int((now - ts).total_seconds() * 1000))
    except Exception:
        duration_ms = 0
    end_row = {
        "ts": now.isoformat(),
        "event": "end",
        "router_id": rid,
        "status": "reconciled",
        "error_code": "stale_orphan",
        "error": "closed by reconcile_router_audit.sh",
        "provider": None,
        "duration_ms": duration_ms,
        "request_id": row.get("request_id"),
        "user_id": row.get("user_id"),
    }
    with solar_state.session() as store:
        store.audit_append(end_row)

print(f"OK: appended {len(orphans)} reconciled end event(s)")
PYEOF
