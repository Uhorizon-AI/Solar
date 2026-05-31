#!/usr/bin/env bash
# reconcile_router_audit.sh — close orphan router audit starts (append synthetic end events).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../solar-interface/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$RESOLVE_SCRIPT"
solar_resolve_paths --quiet

AUDIT_LOG="$SOLAR_WORKSPACE/sun/runtime/router/audit.jsonl"
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

if [[ ! -f "$AUDIT_LOG" ]]; then
  echo "OK: no audit log at $AUDIT_LOG"
  exit 0
fi

export AUDIT_LOG MIN_AGE_HOURS DRY_RUN
python3 - <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

audit_path = Path(os.environ["AUDIT_LOG"])
min_age_hours = float(os.environ.get("MIN_AGE_HOURS", "1"))
dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

starts: dict[str, dict] = {}
ends: set[str] = set()

with audit_path.open(encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
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

with audit_path.open("a", encoding="utf-8") as fh:
    for rid, row in orphans:
        ts_raw = row.get("ts", "")
        duration_ms = None
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
        fh.write(json.dumps(end_row, ensure_ascii=True) + "\n")

print(f"OK: appended {len(orphans)} reconciled end event(s) to {audit_path}")
PYEOF
