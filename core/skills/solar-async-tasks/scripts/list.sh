#!/bin/bash

# List tasks from solar-state. No frontmatter is parsed here.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

export SOLAR_STATE_PY
python3 - <<'PY'
import json, os, subprocess, sys

order = ("draft", "planned", "queued", "active", "completed", "error", "cancelled", "archived")
labels = {"draft": "DRAFTS", "planned": "PLANNED", "queued": "QUEUED", "active": "ACTIVE",
          "completed": "COMPLETED", "error": "ERROR", "cancelled": "CANCELLED", "archived": "ARCHIVE"}
state = os.environ["SOLAR_STATE_PY"]
for status in order:
    proc = subprocess.run([sys.executable, state, "task", "list", "--status", status],
                          text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout)
        sys.exit(proc.returncode)
    rows = json.loads(proc.stdout or "[]")
    print(f"=== {labels[status]} ===")
    for row in rows:
        fields = row.get("fields") or {}
        extra = ""
        if status == "queued":
            when = fields.get("scheduled_time") or ""
            days = fields.get("scheduled_weekdays") or ""
            if when or days:
                extra = " @ " + " ".join(part for part in (when, days) if part)
            if str(fields.get("recurring")).lower() == "true":
                extra += " (recurring)"
            blocked = fields.get("blocked_by_task_ids") or ""
            if blocked:
                extra += f" [blocked: {blocked}]"
        print(f"[{row['id']}] {row.get('title') or ''}{extra}")
    print()
PY
