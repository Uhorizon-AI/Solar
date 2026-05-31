#!/usr/bin/env python3
"""In-memory event feed for Solar Host inbox (MVP-b.1)."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

_MAX_EVENTS = 200
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def emit(event_type: str, payload: dict | None = None) -> dict:
    event = {
        "type": event_type,
        "ts": _now_iso(),
        "payload": payload or {},
    }
    _events.appendleft(event)
    return event


def list_recent(limit: int = 50) -> list[dict]:
    cap = max(1, min(limit, _MAX_EVENTS))
    return list(_events)[:cap]
