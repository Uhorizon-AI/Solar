"""Shim — canonical module: solar-client/scripts/solar_paths.py"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_CLIENT_MODULE = Path(__file__).resolve().parent.parent.parent / "solar-client" / "scripts" / "solar_paths.py"
_spec = importlib.util.spec_from_file_location("solar_paths_client", _CLIENT_MODULE)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load solar_paths from {_CLIENT_MODULE}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

resolve_solar_paths = _mod.resolve_solar_paths
solar_core_path = _mod.solar_core_path
workspace_root = _mod.workspace_root
resolve_under_home = _mod.resolve_under_home

__all__ = [
    "resolve_solar_paths",
    "solar_core_path",
    "workspace_root",
    "resolve_under_home",
]

if __name__ == "__main__":
    import sys

    try:
        ws, root = resolve_solar_paths()
        print(f"SOLAR_WORKSPACE={ws}")
        print(f"SOLAR_ROOT={root}")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
