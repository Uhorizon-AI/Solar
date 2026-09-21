#!/usr/bin/env python3
"""One-shot adoption of the continuity record older routers kept under sun/runtime.

Until v0.25.7 the router wrote `sun/runtime/continuity/active.json` while
everyone else read the runtime copy, so the live intention may be the legacy
one. Every writer of the runtime record (router, continuity_cli) calls
`adopt_legacy` first, so a write can never make the dead copy look newer.

- The newer file wins. Comparison, copy and rename run under one lock.
- The legacy file is renamed to a unique `active.json.migrated-<stamp>`: never
  deleted, never overwriting an earlier backup.
- A legacy file that is already gone is the expected race and is silent. Any
  other disk error is handed to `on_error` and the caller carries on; the next
  call retries.

Delete this module once no install predates the fix.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows: no advisory lock available
    fcntl = None  # type: ignore[assignment]


def legacy_path(workspace: os.PathLike[str] | str) -> Path:
    return Path(workspace) / "sun" / "runtime" / "continuity" / "active.json"


@contextmanager
def _locked(lock_file: Path) -> Iterator[None]:
    with open(lock_file, "a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _unique_backup(legacy: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = legacy.with_name(f"{legacy.name}.migrated-{stamp}")
    n = 1
    while candidate.exists():
        candidate = legacy.with_name(f"{legacy.name}.migrated-{stamp}-{n}")
        n += 1
    return candidate


def adopt_legacy(
    workspace: os.PathLike[str] | str,
    active: Path,
    on_error: Optional[Callable[[OSError], None]] = None,
) -> str:
    """Return "none", "adopted" (legacy copied over) or "kept" (runtime was newer),
    or "failed" after reporting the error through `on_error`."""
    legacy = legacy_path(workspace)
    if not legacy.is_file():
        return "none"
    try:
        active.parent.mkdir(parents=True, exist_ok=True)
        with _locked(active.parent / ".adopt.lock"):
            try:
                legacy_mtime = legacy.stat().st_mtime
            except FileNotFoundError:
                return "none"  # another process adopted it while we waited
            adopt = not active.exists() or legacy_mtime > active.stat().st_mtime
            if adopt:
                tmp = active.with_name(f"{active.name}.adopting-{os.getpid()}")
                tmp.write_bytes(legacy.read_bytes())
                os.replace(tmp, active)
            os.rename(legacy, _unique_backup(legacy))
            return "adopted" if adopt else "kept"
    except FileNotFoundError:
        return "none"
    except OSError as exc:
        if on_error is not None:
            on_error(exc)
        return "failed"
