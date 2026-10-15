"""Listener snapshots for the console port, so a suite can prove it left nothing behind.

Used by core/tests/conftest.py (one snapshot before any test, one after the last)
and by the console harness (per test). A snapshot is taken with lsof; without
lsof it is ``None`` and every comparison passes (nothing can be observed).
"""
from __future__ import annotations

import json
import subprocess
import urllib.request

PRODUCTION_PORT = 9000


def _args(pid: str) -> str:
    try:
        return subprocess.run(["ps", "-ww", "-p", pid, "-o", "args="], capture_output=True, text=True,
                              timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


_IDENTITY_CACHE: dict[tuple[str, str], str] = {}


def _identity(pid: str, address: str) -> str:
    """workspace|runtime a console reports in /health ('' unless it reports BOTH).

    Read over HTTP from the very address that is listening; a listener that does not
    answer, is not a console, or reports no (or partial) identity yields '' and so
    never counts as verified. Cached per (pid, address): one request per listener.
    """
    key = (pid, address)
    if key not in _IDENTITY_CACHE:
        value = ""
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://{address}/health", timeout=2) as response:
                payload = json.load(response)
            workspace, runtime = payload.get("workspace"), payload.get("runtime")
            if payload.get("service") == "solar-console" and workspace and runtime:
                value = f"{workspace}|{runtime}"
        except (OSError, ValueError, AttributeError):
            pass
        _IDENTITY_CACHE[key] = value
    return _IDENTITY_CACHE[key]


def snapshot(port: int = PRODUCTION_PORT) -> frozenset[tuple[str, str, str, str]] | None:
    """Set of (pid, address, command line, identity) listening on the port; None if unobservable."""
    try:
        listed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found: set[tuple[str, str, str, str]] = set()
    pid = ""
    for line in listed.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid:
            found.add((pid, line[1:], _args(pid), _identity(pid, line[1:])))
    return frozenset(found)


def new_listeners(before: frozenset | None, after: frozenset | None) -> frozenset:
    """Listeners now that are not the baseline's.

    Same address and same pid: unchanged. A new pid is accepted as a restart of the
    same program only with evidence: same command line AND the same workspace and
    runtime reported by /health, on both sides. A different command line, a different
    identity, or an identity that cannot be read is treated as a replacement (the
    original incident: a console served from a pytest temp directory, or by the same
    command with another environment). Limit: a replacement that keeps pid, command
    line, address and identity is indistinguishable from the original.
    """
    if before is None or after is None:
        return frozenset()
    leaked = set()
    for pid, address, args, identity in after:
        same = [b for b in before if b[1] == address]
        if any(b[0] == pid and b[2] == args for b in same):
            continue
        if identity and any(b[2] == args and b[3] == identity for b in same):
            continue
        leaked.add((pid, address, args, identity))
    return frozenset(leaked)
