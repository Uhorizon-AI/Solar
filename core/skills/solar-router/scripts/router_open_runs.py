"""Router runs that are still open: a `start` audit row with no `end`.

A cancelled or forced-stopped task kills its router with SIGTERM/SIGKILL, so the router
never writes `end`. A run whose task has left `active` is finished, not in flight.
"""
from __future__ import annotations

from typing import Callable, Optional

from solar_state import TERMINAL_STATUSES  # a task never leaves these: its router run cannot be running


def run_task_id(row: dict) -> Optional[str]:
    """The task a run belongs to: the restricted route records task_id, others use request_id."""
    task_id = row.get("task_id")
    if task_id:
        return str(task_id)
    # The executor sends request_id=f"task_{task_id}" (execute_active.call_router).
    request_id = str(row.get("request_id") or "")
    return request_id[len("task_"):] or None if request_id.startswith("task_") else None


def open_runs(rows: list[dict], task_status: Callable[[str], Optional[str]]) -> dict[str, dict]:
    """router_id -> start row, for starts with no end whose task is not terminal.

    A task the store does not know stays open: nothing proves the run is over."""
    starts: dict[str, dict] = {}
    ends: set[str] = set()
    for row in rows:
        rid = row.get("router_id", "")
        if row.get("event") == "start":
            starts[rid] = row
        elif row.get("event") == "end":
            ends.add(rid)
    result = {}
    for rid, row in starts.items():
        if rid in ends:
            continue
        task_id = run_task_id(row)
        if task_id and task_status(task_id) in TERMINAL_STATUSES:
            continue
        result[rid] = row
    return result
