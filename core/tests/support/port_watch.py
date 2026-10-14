"""Listener snapshots for the console port, so a suite can prove it left nothing behind.

Used by core/tests/conftest.py (one snapshot before any test, one after the last)
and by the console harness (per test). A snapshot is taken with lsof; without
lsof it is ``None`` and every comparison passes (nothing can be observed).
"""
from __future__ import annotations

import subprocess

PRODUCTION_PORT = 9000


def snapshot(port: int = PRODUCTION_PORT) -> frozenset[tuple[str, str]] | None:
    """Set of (pid, address) currently listening on the port; None if unobservable."""
    try:
        listed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found: set[tuple[str, str]] = set()
    pid = ""
    for line in listed.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid:
            found.add((pid, line[1:]))
    return frozenset(found)


def new_listeners(before: frozenset | None, after: frozenset | None) -> frozenset:
    """Listeners present now that were not there in the baseline."""
    if before is None or after is None:
        return frozenset()
    return after - before
