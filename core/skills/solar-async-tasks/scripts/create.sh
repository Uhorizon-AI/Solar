#!/bin/bash

# Create a task through solar-state. Nothing is written under async-tasks/.
# Default status is draft. --queued creates it already queued.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=task_lib.sh
source "$SCRIPT_DIR/task_lib.sh"

DEST="draft"
PRIORITY="normal"
SCHEDULED_TIME=""
BODY_FILE=""
PROVIDER=""
METADATA_JSON=""
PARENT_TASK_ID=""
SUBTASK_KEY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --queued)         DEST="queued"; shift ;;
        --priority)       PRIORITY="$2"; shift 2 ;;
        --scheduled-time) SCHEDULED_TIME="$2"; shift 2 ;;
        --body-file)      BODY_FILE="$2"; shift 2 ;;
        --provider)       PROVIDER="$2"; shift 2 ;;
        --metadata)       METADATA_JSON="$2"; shift 2 ;;
        --parent-task-id) PARENT_TASK_ID="$2"; shift 2 ;;
        --subtask-key)    SUBTASK_KEY="$2"; shift 2 ;;
        --origin-channel|--origin-chat-id|--origin-request-id)
            echo "Unknown option: $1 (use --metadata JSON)" >&2
            exit 1
            ;;
        --) shift; break ;;
        -*) echo "Unknown option: $1" >&2; exit 1 ;;
        *) break ;;
    esac
done

TITLE="${1:-}"
DESCRIPTION="${2:-}"

if [[ -z "$TITLE" ]]; then
    echo "Usage: create.sh [OPTIONS] \"Task Title\" [\"Description\"]" >&2
    exit 1
fi

if [[ "$DEST" != "queued" && ( -n "$PARENT_TASK_ID" || -n "$SUBTASK_KEY" ) ]]; then
    echo "Error: --parent-task-id and --subtask-key require --queued." >&2
    exit 1
fi

case "$PRIORITY" in
    high|normal|low) ;;
    *) echo "Error: --priority must be high, normal or low (got: $PRIORITY)" >&2; exit 1 ;;
esac

if [[ -n "$BODY_FILE" && ! -f "$BODY_FILE" ]]; then
    echo "Error: body file not found: $BODY_FILE" >&2
    exit 1
fi

CREATED="$(date -Iseconds)"
export SOLAR_CREATE_TITLE="$TITLE"
export SOLAR_CREATE_DESCRIPTION="$DESCRIPTION"
export SOLAR_CREATE_BODY_FILE="${BODY_FILE:-}"
export SOLAR_CREATE_DEST="$DEST"
export SOLAR_CREATE_PRIORITY="$PRIORITY"
export SOLAR_CREATE_SCHEDULED="${SCHEDULED_TIME:-}"
export SOLAR_CREATE_PROVIDER="${PROVIDER:-}"
export SOLAR_CREATE_PARENT="${PARENT_TASK_ID:-}"
export SOLAR_CREATE_KEY="${SUBTASK_KEY:-}"
export SOLAR_CREATE_META="${METADATA_JSON:-}"
export SOLAR_CREATE_CREATED="$CREATED"
export SOLAR_STATE_PY

python3 - <<'PY'
import json, os, subprocess, sys, tempfile
from pathlib import Path

def quoted(value):
    return json.dumps(value, ensure_ascii=False)

title = os.environ["SOLAR_CREATE_TITLE"]
description = os.environ.get("SOLAR_CREATE_DESCRIPTION") or ""
body_file = os.environ.get("SOLAR_CREATE_BODY_FILE") or ""
dest = os.environ["SOLAR_CREATE_DEST"]
priority = os.environ["SOLAR_CREATE_PRIORITY"]
body = Path(body_file).read_text(encoding="utf-8") if body_file else description

meta = {}
raw = os.environ.get("SOLAR_CREATE_META") or ""
if raw:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Error: --metadata must be a JSON object (flat origin_* or nested origin).", file=sys.stderr)
        sys.exit(1)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        print("Error: --metadata must be a JSON object (flat origin_* or nested origin).", file=sys.stderr)
        sys.exit(1)
    origin = data.get("origin") if isinstance(data.get("origin"), dict) else {}

    def pick(flat, nested=None):
        value = data.get(flat)
        if value is None and nested is not None:
            value = origin.get(nested)
        if value is None:
            return ""
        return " ".join(str(value).split())

    meta = {
        "origin_channel": pick("origin_channel", "channel"),
        "origin_chat_id": pick("origin_chat_id", "chat_id"),
        "origin_request_id": pick("origin_request_id", "request_id"),
        "object": pick("object"),
        "scope": pick("scope"),
        "effect": pick("effect"),
        "delivery_expected": "true" if data.get("delivery_expected") is True else "",
    }

fields = [
    ("title", quoted(title)),
    ("created", quoted(os.environ["SOLAR_CREATE_CREATED"])),
    ("priority", priority),
]
if dest == "queued":
    fields.append(("scheduled_time", quoted(os.environ.get("SOLAR_CREATE_SCHEDULED") or "now")))
    fields.append(("recurring", "false"))
    for name, env in (
        ("provider", "SOLAR_CREATE_PROVIDER"),
        ("parent_task_id", "SOLAR_CREATE_PARENT"),
        ("subtask_key", "SOLAR_CREATE_KEY"),
    ):
        value = os.environ.get(env) or ""
        if value:
            fields.append((name, quoted(value)))
    for key in ("origin_channel", "origin_chat_id", "origin_request_id", "object", "scope", "effect"):
        if meta.get(key):
            fields.append((key, quoted(meta[key])))
    if meta.get("delivery_expected"):
        fields.append(("delivery_expected", "true"))
    if any(meta.get(key) for key in ("origin_channel", "origin_chat_id", "origin_request_id")):
        fields.append(("notify_when", "completed"))

document = "\n# " + title + "\n\n" + body
with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
    handle.write(document)
    path = handle.name
cmd = [sys.executable, os.environ["SOLAR_STATE_PY"], "task", "create", "--status", dest, "--body-file", path]
for key, value in fields:
    cmd.extend(["--field", f"{key}={value}"])
try:
    proc = subprocess.run(cmd, text=True, capture_output=True)
finally:
    Path(path).unlink(missing_ok=True)
if proc.returncode != 0:
    detail = (proc.stderr or proc.stdout or "task create failed").strip()
    print(detail, file=sys.stderr)
    sys.exit(proc.returncode)
created = json.loads(proc.stdout)
task_id = created["id"]
parent = os.environ.get("SOLAR_CREATE_PARENT") or ""
key = os.environ.get("SOLAR_CREATE_KEY") or ""
if parent:
    # The child already carries parent_task_id. The link row needs the parent
    # to be a row; a child published on its own still stands.
    state = os.environ["SOLAR_STATE_PY"]
    known = subprocess.run(
        [sys.executable, state, "task", "status", parent],
        text=True, capture_output=True,
    )
    if known.returncode == 0:
        link = [sys.executable, state, "task", "link", parent, task_id]
        if key:
            link.extend(["--key", key])
        linked = subprocess.run(link, text=True, capture_output=True)
        if linked.returncode != 0:
            detail = (linked.stderr or linked.stdout or "task link failed").strip()
            print(detail, file=sys.stderr)
            sys.exit(linked.returncode)
print(f"Task created: {task_id}")
print(f"ID: {task_id}")
PY
