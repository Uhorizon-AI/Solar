"""Listener snapshots for the console port, so a suite can prove it left nothing behind.

Used by core/tests/conftest.py (one snapshot before any test, one after the last)
and by the console harness (per test). A snapshot is taken with lsof; without
lsof it is ``None`` and every comparison passes (nothing can be observed).
"""
from __future__ import annotations

import subprocess

PRODUCTION_PORT = 9000


def _args(pid: str) -> str:
    try:
        return subprocess.run(["ps", "-ww", "-p", pid, "-o", "args="], capture_output=True, text=True,
                              timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def snapshot(port: int = PRODUCTION_PORT) -> frozenset[tuple[str, str, str]] | None:
    """Set of (pid, address, command line) listening on the port; None if unobservable."""
    try:
        listed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found: set[tuple[str, str, str]] = set()
    pid = ""
    for line in listed.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid:
            found.add((pid, line[1:], _args(pid)))
    return frozenset(found)


def new_listeners(before: frozenset | None, after: frozenset | None) -> frozenset:
    """Listeners now that are not the baseline's.

    A listener is a leak if its address had none in the baseline, or if it runs a
    different command line than the baseline's listener on that address: a console
    replaced by one served from another place (the original incident) is caught.
    The same command line with a new pid is the same program restarted (a
    developer's console restarted by its LaunchAgent during the run) and is not.
    """
    if before is None or after is None:
        return frozenset()
    known = {(address, args) for _, address, args in before}
    return frozenset(entry for entry in after if (entry[1], entry[2]) not in known)
