#!/usr/bin/env python3
"""Resolve workspace-scoped InterfaceStore for Solar Host (in-process API)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_CORE_DIR = _SCRIPT_DIR.parent.parent.parent
_INTERFACE_SCRIPTS = _CORE_DIR / "skills" / "solar-interface" / "scripts"

if str(_INTERFACE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_INTERFACE_SCRIPTS))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from interface_store import InterfaceStore  # noqa: E402

import host_registry as reg  # noqa: E402
import host_workspace_context as ctx  # noqa: E402

_cache: dict[str, InterfaceStore] = {}


def _workspace_path(workspace: str | None = None) -> str:
    ws = workspace or ctx.get_mounted() or reg.get_active_path()
    if not ws:
        raise ValueError("no workspace mounted or active")
    return str(Path(ws).resolve())


def get_store(workspace: str | None = None) -> InterfaceStore:
    norm = _workspace_path(workspace)
    if norm not in _cache:
        store = InterfaceStore(norm)
        store.ensure_runtime()
        _cache[norm] = store
    return _cache[norm]


def invalidate_store(workspace: str | None = None) -> None:
    if workspace:
        _cache.pop(str(Path(workspace).resolve()), None)
    else:
        _cache.clear()
