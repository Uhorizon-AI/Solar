"""Test helper: the execution token of the reservation a claim just took."""
from __future__ import annotations

from typing import Optional


def token_of(store, task_id: str) -> Optional[str]:
    """The current token of `task_id`, or None when it holds no reservation (a task that is
    not active, or one that was active before reservations existed)."""
    row = store.conn.execute("SELECT token FROM execution_reservations WHERE task_id = ?",
                             (task_id,)).fetchone()
    return row[0] if row else None
