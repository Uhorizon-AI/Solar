#!/usr/bin/env python3
"""Py2app entry — Solar.app menu bar tray (notifications show as Solar, not Python)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from host_platform.macos.tray import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
