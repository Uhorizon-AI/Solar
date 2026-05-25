#!/usr/bin/env bash
# status_router.sh — Solar Router live status
# Shows: provider health, in-flight processes, last executions
# Usage: bash core/skills/solar-router/scripts/status_router.sh [--last N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../solar-interface/scripts" && pwd)/resolve_solar_paths.sh"
# shellcheck source=/dev/null
source "$RESOLVE_SCRIPT"
solar_resolve_paths --quiet
SOLAR_WORKSPACE="${SOLAR_WORKSPACE:-$SOLAR_WORKSPACE}"
AUDIT_LOG="$SOLAR_WORKSPACE/sun/runtime/router/audit.jsonl"
PYTHON="${SOLAR_AI_ROUTER_PYTHON:-python3}"
LAST_N=10

STALE_COUNT_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --last) shift; LAST_N="${1:-10}"; shift ;;
    --stale-count) STALE_COUNT_ONLY=true; shift ;;
    *) shift ;;
  esac
done

if [[ "$STALE_COUNT_ONLY" == true ]]; then
  if [[ ! -f "$AUDIT_LOG" ]]; then
    echo "0"
    exit 0
  fi
  $PYTHON - "$AUDIT_LOG" <<'PYEOF'
import json, sys
audit_path = sys.argv[1]
starts = {}
ends = set()
with open(audit_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = row.get("router_id", "")
        if row.get("event") == "start":
            starts[rid] = row
        elif row.get("event") == "end":
            ends.add(rid)
print(len([rid for rid in starts if rid not in ends]))
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
  | grep -E "^\s+- (codex|claude|gemini)" \
  | sed 's/^/  /' \
  || echo "    (diagnose_router.sh not available)"

# ---------------------------------------------------------------------------
# 2. In-flight processes (start without matching end)
# ---------------------------------------------------------------------------
echo ""
echo "  In-flight:"

if [[ ! -f "$AUDIT_LOG" ]]; then
  echo "    (no audit log yet)"
else
  $PYTHON - "$AUDIT_LOG" <<'PYEOF'
import json, sys, datetime

audit_path = sys.argv[1]
starts = {}
ends = set()

with open(audit_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
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
fi

# ---------------------------------------------------------------------------
# 3. Last N executions
# ---------------------------------------------------------------------------
echo ""
echo "  Last $LAST_N executions:"

if [[ ! -f "$AUDIT_LOG" ]]; then
  echo "    (no audit log yet)"
else
  $PYTHON - "$AUDIT_LOG" "$LAST_N" <<'PYEOF'
import json, sys

audit_path = sys.argv[1]
last_n = int(sys.argv[2])

starts = {}
ends = {}

with open(audit_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
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
fi

echo ""
echo "══════════════════════════════════════════════"
echo ""
