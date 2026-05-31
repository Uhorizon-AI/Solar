#!/usr/bin/env python3
"""In-memory event feed for Solar Host inbox (MVP-b.1+)."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

_MAX_EVENTS = 200
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def emit(event_type: str, payload: dict | None = None, *, workspace: str | None = None) -> dict:
    body = dict(payload or {})
    if workspace and "workspace" not in body:
        body["workspace"] = workspace
    event = {
        "type": event_type,
        "ts": _now_iso(),
        "payload": body,
    }
    _events.appendleft(event)
    return event


def list_recent(limit: int = 50, types: set[str] | None = None) -> list[dict]:
    items = list(_events)
    if types:
        items = [e for e in items if e.get("type") in types]
    cap = max(1, min(limit, _MAX_EVENTS))
    return items[:cap]


def clear() -> None:
    """Reset feed (tests only)."""
    _events.clear()
