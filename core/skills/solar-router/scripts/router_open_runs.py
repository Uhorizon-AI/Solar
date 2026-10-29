"""Router runs that are still open: a `start` audit row with no `end`.

A cancelled or forced-stopped task kills its router with SIGTERM/SIGKILL, so the router
never writes `end`. A run whose task has left `active` is finished, not in flight.
"""
from __future__ import annotations

import datetime
from typing import Callable, Optional

from solar_state import TERMINAL_STATUSES  # a task never leaves these: its router run cannot be running


def run_task_id(row: dict) -> Optional[str]:
    """The task a run belongs to: the restricted route records task_id, others use request_id."""
    task_id = row.get("task_id")
    if task_id:
        return str(task_id)
    # The executor sends request_id=f"task_{task_id}" (execute_active.call_router).
    request_id = str(row.get("request_id") or "")
    if not request_id.startswith("task_"):
        return None
    return request_id[len("task_"):] or None


def _parse(ts: object) -> Optional[datetime.datetime]:
    try:
        parsed = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def last_claim(store) -> Callable[[str], Optional[str]]:
    """task_id -> when the task last became active: the start of its current attempt."""
    def lookup(task_id: str) -> Optional[str]:
        row = store.conn.execute(
            "SELECT MAX(ts) FROM task_events WHERE task_id = ? AND to_status = 'active'",
            (task_id,)).fetchone()
        return row[0] if row else None
    return lookup


def open_runs(rows: list[dict], task_status: Callable[[str], Optional[str]],
              task_claimed: Callable[[str], Optional[str]] = lambda task_id: None) -> dict[str, dict]:
    """router_id -> start row, for starts with no end that can still be running.

    Not running: the task is terminal, or the task became active again after the run started
    (a retry or requeue: that attempt is over). A task the store does not know stays open:
    nothing proves the run is over."""
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
        if task_id:
            if task_status(task_id) in TERMINAL_STATUSES:
                continue
            started, claimed = _parse(row.get("ts")), _parse(task_claimed(task_id))
            if started and claimed and started < claimed:
                continue
        result[rid] = row
    return result
