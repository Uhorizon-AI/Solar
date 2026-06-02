#!/usr/bin/env python3
"""In-memory event feed for Solar Host inbox (MVP-b.1+)."""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

_MAX_EVENTS = 200
_COOLDOWN_SEC = 300
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)
_last_dedupe: dict[tuple[str, str, str], float] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dedupe_key(event_type: str, payload: dict, workspace: str | None) -> str:
    explicit = str(payload.get("dedupe_key") or "").strip()
    if explicit:
        return explicit
    parts = [
        str(payload.get("workspace") or workspace or ""),
        str(payload.get("path") or ""),
        str(payload.get("severity") or ""),
        str(payload.get("action") or ""),
        str(payload.get("summary") or "")[:120],
    ]
    return "|".join(parts)


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


def emit_deduped(
    event_type: str,
    payload: dict | None = None,
    *,
    workspace: str | None = None,
    cooldown_sec: float | None = None,
) -> dict | None:
    """Emit once per (type, workspace, dedupe_key) within cooldown (default 5 min)."""
    body = dict(payload or {})
    ws = str(body.get("workspace") or workspace or "")
    key = (event_type, ws, _dedupe_key(event_type, body, workspace))
    now = time.time()
    window = _COOLDOWN_SEC if cooldown_sec is None else float(cooldown_sec)
    last = _last_dedupe.get(key)
    if last is not None and now - last < window:
        return None
    _last_dedupe[key] = now
    return emit(event_type, body, workspace=workspace or ws or None)


def list_recent(limit: int = 50, types: set[str] | None = None) -> list[dict]:
    items = list(_events)
    if types:
        items = [e for e in items if e.get("type") in types]
    cap = max(1, min(limit, _MAX_EVENTS))
    return items[:cap]


def clear() -> None:
    """Reset feed (tests only)."""
    _events.clear()
    _last_dedupe.clear()
