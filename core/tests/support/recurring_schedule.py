"""A schedule that is open now, for tests that run a recurring task: a recurring task needs a clock time."""
from __future__ import annotations

from datetime import datetime, timezone


def open_now(moment: datetime | None = None) -> dict:
    """Frontmatter values (already quoted) for a daily schedule in UTC whose window holds `moment`."""
    at = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {"scheduled_time": f'"{at:%H:%M}"', "scheduled_timezone": '"UTC"'}
