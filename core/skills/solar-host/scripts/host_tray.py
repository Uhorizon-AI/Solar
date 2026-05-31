#!/usr/bin/env python3
"""Thin entrypoint — delegates to host_platform/macos/tray.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from host_platform.macos.tray import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
