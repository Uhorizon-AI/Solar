"""Router runs that are still open: a `start` audit row with no `end`.

A cancelled or forced-stopped task kills its router with SIGTERM/SIGKILL, so the router
never writes `end`. A run whose task has left `active` is finished, not in flight.
"""
from __future__ import annotations

import datetime
from typing import Callable, Optional


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


def parse_ts(ts: object) -> Optional[datetime.datetime]:
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

    Not running: the task is known and not `active` (finished, or requeued and waiting), the task
    became active again after the run started (a retry), or a later run of the same task exists
    (a task has one live run). The audit keeps microseconds and task events only seconds, so the
    last rule also covers a retry inside the same second. A task the store does not know stays
    open: nothing proves the run is over."""
    starts: dict[str, dict] = {}
    ends: set[str] = set()
    for row in rows:
        rid = row.get("router_id", "")
        if row.get("event") == "start":
            starts[rid] = row
        elif row.get("event") == "end":
            ends.add(rid)
    result: dict[str, dict] = {}
    latest: dict[str, str] = {}       # task_id -> router_id of its newest start, ended or not
    for rid, row in starts.items():
        task_id = run_task_id(row)
        if task_id:
            latest[task_id] = rid
    for rid, row in starts.items():
        if rid in ends:
            continue
        task_id = run_task_id(row)
        if task_id:
            status = task_status(task_id)
            if status is not None and status != "active":
                continue
            if latest[task_id] != rid:
                continue
            started, claimed = parse_ts(row.get("ts")), parse_ts(task_claimed(task_id))
            if started and claimed and started < claimed:
                continue
        result[rid] = row
    return result
