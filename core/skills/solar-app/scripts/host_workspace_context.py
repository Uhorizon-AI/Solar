#!/usr/bin/env python3
"""Mount / unmount / switch active workspace context for Solar Host."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import host_registry as reg  # noqa: E402

_mounted: str | None = None
_managed_env_keys: set[str] = set()
_CORE_DIR = _SCRIPT_DIR.parent.parent.parent


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def parse_workspace_env_file(ws: Path | str) -> dict[str, str]:
    ws_path = Path(ws).resolve()
    env_file = ws_path / ".env"
    out: dict[str, str] = {}
    if not env_file.is_file():
        return out
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def _clear_workspace_env() -> None:
    global _managed_env_keys  # noqa: PLW0603
    for key in _managed_env_keys:
        os.environ.pop(key, None)
    _managed_env_keys = set()


def load_workspace_env(ws: Path | str) -> None:
    """Apply workspace .env to process env, replacing keys from the previous mount."""
    global _managed_env_keys  # noqa: PLW0603
    ws_path = Path(ws).resolve()
    _clear_workspace_env()
    retired_ports = {"SOLAR_APP_PORT", "SOLAR_HOST_PORT", "SOLAR_INTERFACE_PORT"}
    for key, val in parse_workspace_env_file(ws_path).items():
        if key in retired_ports:
            continue
        os.environ[key] = val
        _managed_env_keys.add(key)
    os.environ["SOLAR_WORKSPACE"] = str(ws_path)
    _managed_env_keys.add("SOLAR_WORKSPACE")
    _apply_legacy_app_env()
    os.environ["SOLAR_APP_PORT"] = "9000"
    _managed_env_keys.add("SOLAR_APP_PORT")


def _apply_legacy_app_env() -> None:
    """Map deprecated SOLAR_HOST_* / SOLAR_INTERFACE_* keys to SOLAR_APP_*."""
    global _managed_env_keys  # noqa: PLW0603
    if not os.environ.get("SOLAR_APP_HOST"):
        for key in ("SOLAR_HOST_HOST", "SOLAR_INTERFACE_HOST"):
            val = os.environ.get(key)
            if val:
                os.environ["SOLAR_APP_HOST"] = val
                _managed_env_keys.add("SOLAR_APP_HOST")
                break


def get_mounted() -> str | None:
    return _mounted


def mount(path: str) -> str:
    global _mounted  # noqa: PLW0603
    norm = _normalize_path(path)
    if not Path(norm).is_dir():
        raise ValueError(f"workspace not found: {path}")
    load_workspace_env(norm)
    _mounted = norm
    return norm


def unmount() -> None:
    global _mounted  # noqa: PLW0603
    old = _mounted
    if not old:
        return
    _clear_workspace_env()
    _mounted = None


def switch_workspace(path: str) -> str:
    old = get_mounted()
    norm_new = _normalize_path(path)
    if old and _normalize_path(old) != norm_new:
        unmount()
    reg.set_active(path)
    mounted = mount(path)
    reg.record_metric(
        "workspace.switch",
        {"from": old or "", "to": mounted},
    )
    return mounted
