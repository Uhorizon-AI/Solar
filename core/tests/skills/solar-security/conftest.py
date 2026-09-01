"""Pytest bootstrapping for solar-security: make skill scripts importable."""
from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parents[3]
_SCRIPTS = _CORE / "skills" / "solar-security" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
