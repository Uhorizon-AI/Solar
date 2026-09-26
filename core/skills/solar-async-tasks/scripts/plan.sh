#!/bin/bash

# draft -> planned, and append the planning template to the body once.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"

if [[ -z "$TASK_ID" ]]; then
    echo "Usage: $0 <task_id>" >&2
    exit 1
fi

state task transition "$TASK_ID" planned --from draft >/dev/null

export SOLAR_PLAN_ID="$TASK_ID"
export SOLAR_STATE_PY
python3 - <<'PY'
import json, os, subprocess, sys
show = subprocess.run(
    [sys.executable, os.environ["SOLAR_STATE_PY"], "task", "get", os.environ["SOLAR_PLAN_ID"]],
    text=True, capture_output=True)
if show.returncode != 0:
    sys.stderr.write(show.stderr or show.stdout)
    sys.exit(show.returncode)
body = json.loads(show.stdout).get("body") or ""
if "# Implementation Plan" in body:
    sys.exit(0)
extra = (
    "\n# Implementation Plan\n\n"
    "- [ ] Technical Design\n"
    "- [ ] Dependencies\n"
    "- [ ] Verification Steps\n"
)
proc = subprocess.run(
    [sys.executable, os.environ["SOLAR_STATE_PY"], "task", "write-body", os.environ["SOLAR_PLAN_ID"]],
    input=body + extra, text=True, capture_output=True)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr or proc.stdout)
    sys.exit(proc.returncode)
PY

echo "Task $TASK_ID moved to planned."
