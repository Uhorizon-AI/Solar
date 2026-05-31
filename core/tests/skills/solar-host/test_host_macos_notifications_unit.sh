#!/usr/bin/env bash
# Host-1: unit tests for macOS notification subscriber (no Notification Center / rumps).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-host/scripts"
PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    FAIL=$((FAIL + 1))
  fi
}

UNIT_EXIT=0
python3 - <<'PY' "$SCRIPTS" || UNIT_EXIT=$?
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts))

from host_platform.macos import notifications

seen: Set[str] = set()
events = [
    {
        "type": "approval.pending",
        "ts": "2026-05-31T12:00:00+00:00",
        "payload": {"approval_id": "appr_1", "summary": "deploy"},
    },
    {
        "type": "approval.pending",
        "ts": "2026-05-31T12:00:00+00:00",
        "payload": {"approval_id": "appr_1", "summary": "deploy"},
    },
    {
        "type": "run.completed",
        "ts": "2026-05-31T12:01:00+00:00",
        "payload": {"run_id": "run_1"},
    },
    {
        "type": "run.failed",
        "ts": "2026-05-31T12:02:00+00:00",
        "payload": {"run_id": "run_2", "summary": "boom"},
    },
]

fresh = notifications.process_events(events, seen)
assert len(fresh) == 2, fresh
assert notifications.should_notify("approval.pending")
assert not notifications.should_notify("run.completed")

url = notifications.dashboard_focus_url(fresh[0], base="http://127.0.0.1:9000")
assert "focus=approval:appr_1" in url, url

shown: List[Tuple[str, str, str, Optional[str]]] = []

def _mock_show(title, subtitle, message, open_url=None):
    shown.append((title, subtitle, message, open_url))

n = notifications.notify_events(fresh, set(), show_fn=_mock_show)
assert n == 2, n
assert shown[0][3] and "appr_1" in shown[0][3], shown

# Second pass dedupes
again = notifications.process_events(events, seen)
assert again == [], again

# Solar.app path uses terminal-notifier with -sender (never rumps — registers Python).
calls: List[str] = []

def _fake_tn_cmd(title, subtitle, message, *, open_url=None):
    calls.append(f"tn:{open_url or ''}")
    return True

notifications.running_in_solar_app = lambda: True
notifications._notify_via_terminal_notifier = _fake_tn_cmd
notifications.show_notification("Solar", "t", "m", open_url="http://x")
assert calls == ["tn:http://x"], calls

print("OK: notifications unit")
PY

assert_ok "notifications subscriber unit" test "$UNIT_EXIT" -eq 0

LAUNCH_EXIT=0
python3 - <<'PY' "$SCRIPTS" || LAUNCH_EXIT=$?
import os
import sys
from pathlib import Path

scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts))

from host_platform.macos import launch

os.environ.pop("SOLAR_HOST_TRAY", None)
assert launch.start_tray_detached() is False
os.environ["SOLAR_HOST_TRAY"] = "1"
# Do not actually spawn tray in CI; only verify gate when not darwin or missing flag
print("OK: launch gate")
PY

assert_ok "launch tray gate" test "$LAUNCH_EXIT" -eq 0

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
