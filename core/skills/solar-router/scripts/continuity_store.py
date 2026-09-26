#!/usr/bin/env python3
"""One-shot adoption of the continuity record older routers kept under sun/runtime.

The record itself lives in solar-state. This module only names the legacy path
and asks solar-state to copy it. It does not open that file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Optional

_STATE = Path(__file__).resolve().parents[2] / "solar-state" / "scripts"
if str(_STATE) not in sys.path:
    sys.path.insert(0, str(_STATE))

import solar_state  # noqa: E402


def legacy_path(workspace: os.PathLike[str] | str) -> Path:
    return Path(workspace) / "sun" / "runtime" / "continuity" / "active.json"


def adopt_legacy(
    workspace: os.PathLike[str] | str,
    active: Path,
    on_error: Optional[Callable[[OSError], None]] = None,
) -> str:
    """Return "none", "adopted", "kept" or "failed". `active` is unused: the
    row is in solar-state, not a runtime file."""
    del active
    try:
        with solar_state.session() as store:
            return store.continuity_adopt_legacy(workspace)
    except OSError as exc:
        if on_error is not None:
            on_error(exc)
        return "failed"
