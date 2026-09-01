#!/usr/bin/env python3
"""Cross-platform application data paths for Solar Host registry and metrics."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_data_dir() -> Path:
    override = os.environ.get("SOLAR_APP_DATA", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser().resolve()
    return Path.home() / ".local" / "share"


def host_global_dir() -> Path:
    return app_data_dir() / "Solar"
