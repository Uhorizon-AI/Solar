"""Cancellation through solar-state. This does not write a request file.

CLI: task_cancel.py <ignored-root> <task-id>
A queued task becomes cancelled. An active task keeps running and records the
request; the worker acknowledges it with complete.sh.
"""
import json
import sys
from pathlib import Path

_STATE = Path(__file__).resolve().parents[2] / "solar-state" / "scripts"
if str(_STATE) not in sys.path:
    sys.path.insert(0, str(_STATE))

import solar_state  # noqa: E402


def requested(_root, task_id: str) -> bool:
    with solar_state.session() as store:
        return store.cancellation_requested(task_id)


def request(_root, task_id: str) -> dict:
    with solar_state.session() as store:
        return store.task_cancel(task_id)


if __name__ == "__main__":
    task_id = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
    print(json.dumps(request(None, task_id)))
