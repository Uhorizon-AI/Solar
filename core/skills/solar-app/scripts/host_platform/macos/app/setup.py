"""Build Solar.app: uv run --project ... python setup.py py2app (see build_solar_tray_app.sh)."""
from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup

# Staged build: host_platform under ./scripts/ (see build_solar_tray_app.sh).
_STAGE_SCRIPTS = Path(__file__).resolve().parent / "scripts"
_REPO_SCRIPTS = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPTS = _STAGE_SCRIPTS if (_STAGE_SCRIPTS / "host_platform").is_dir() else _REPO_SCRIPTS
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

APP = ["tray_entry.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Solar",
        "CFBundleDisplayName": "Solar",
        "CFBundleIdentifier": "ai.uhorizon.solar.host",
        "LSUIElement": True,
        "NSHumanReadableCopyright": "Solar Host",
        "NSMicrophoneUsageDescription": (
            "Solar usa el micrófono para dictado por voz (transcripción local con Whisper)."
        ),
    },
    "packages": ["rumps", "host_platform"],
    "includes": [
        "host_platform",
        "host_platform.macos",
        "host_platform.macos.tray",
        "host_platform.macos.client",
        "host_platform.macos.notifications",
        "host_platform.macos.launch",
        "host_platform.macos.hotkey",
        "host_platform.macos.voice_tts",
        "host_platform.paths",
        "voice_core",
        "voice_config",
        "voice_mic",
        "host_registry",
        "host_workspace_context",
    ],
}

setup(
    name="Solar",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
