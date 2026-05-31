#!/usr/bin/env python3
"""Optional detached tray process when SOLAR_HOST_TRAY=1 (macOS only)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

_TRAY_SCRIPT = Path(__file__).resolve().parent.parent.parent / "host_tray.py"


def _tray_command() -> List[str]:
    """Prefer built Solar.app (py2app), else `uv run --with rumps`."""
    import shutil

    from host_platform.macos.notifications import solar_app_bundle

    bundle = solar_app_bundle()
    if bundle is not None:
        return [str(bundle / "Contents" / "MacOS" / "Solar")]
    script = str(_TRAY_SCRIPT)
    if shutil.which("uv"):
        return ["uv", "run", "--with", "rumps", "python3", script]
    return [sys.executable, script]


def start_tray_detached() -> bool:
    if sys.platform != "darwin":
        return False
    if os.environ.get("SOLAR_HOST_TRAY", "").strip() != "1":
        return False
    if not _TRAY_SCRIPT.is_file():
        return False
    env = {**os.environ}
    log = os.environ.get("SOLAR_HOST_TRAY_LOG", "").strip()
    if log:
        log_path = Path(log).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        subprocess.Popen(
            _tray_command(),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    else:
        subprocess.Popen(
            _tray_command(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    return True


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] == "start-tray":
        if start_tray_detached():
            print("OK: Solar Host tray starting (SOLAR_HOST_TRAY=1)")
            return 0
        print("SKIP: tray not started (set SOLAR_HOST_TRAY=1 on macOS)")
        return 0
    print(f"Unknown command: {args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
