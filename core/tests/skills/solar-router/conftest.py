"""Pytest bootstrapping for solar-router: make core/skills/solar-router/scripts importable."""
from __future__ import annotations

import sys
from pathlib import Path

# core/tests/skills/solar-router/conftest.py -> parents[3] == core/
_CORE = Path(__file__).resolve().parents[3]
_ROUTER_SCRIPTS = _CORE / "skills" / "solar-router" / "scripts"
if str(_ROUTER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ROUTER_SCRIPTS))
