#!/usr/bin/env python3
"""Mount / unmount / switch active workspace context for Solar Host."""
from __future__ import annotations

import os
import subprocess
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
    for key, val in parse_workspace_env_file(ws_path).items():
        os.environ[key] = val
        _managed_env_keys.add(key)
    os.environ["SOLAR_WORKSPACE"] = str(ws_path)
    _managed_env_keys.add("SOLAR_WORKSPACE")


def legacy_interface_db_path(ws: Path | str) -> Path:
    return Path(ws) / "sun/runtime/interface/db/interface.sqlite"


def legacy_interface_runtime_dir(ws: Path | str) -> Path:
    return Path(ws) / "sun/runtime/interface"


def ensure_workspace_runtime(ws: Path | str) -> None:
    base = legacy_interface_runtime_dir(ws)
    (base / "db").mkdir(parents=True, exist_ok=True)
    (base / "state").mkdir(parents=True, exist_ok=True)
    (base / "db" / "migrations").mkdir(parents=True, exist_ok=True)


def _workspace_subprocess_env(ws: str) -> dict[str, str]:
    """Subprocess env scoped to one workspace (no SOLAR_* leak from another mount)."""
    ws_path = Path(ws).resolve()
    env = {
        k: v
        for k, v in os.environ.items()
        if isinstance(v, str) and not k.startswith("SOLAR_")
    }
    env.update(parse_workspace_env_file(ws_path))
    env["SOLAR_WORKSPACE"] = str(ws_path)
    return env


def _stop_interface_script() -> Path | None:
    root = os.environ.get("SOLAR_ROOT", "").strip()
    if root:
        candidate = Path(root) / "core/skills/solar-interface/scripts/stop_interface_daemon.sh"
        if candidate.is_file():
            return candidate
    candidate = _CORE_DIR / "skills/solar-interface/scripts/stop_interface_daemon.sh"
    return candidate if candidate.is_file() else None


def get_mounted() -> str | None:
    return _mounted


def mount(path: str) -> str:
    global _mounted  # noqa: PLW0603
    norm = _normalize_path(path)
    if not Path(norm).is_dir():
        raise ValueError(f"workspace not found: {path}")
    ensure_workspace_runtime(norm)
    load_workspace_env(norm)
    _mounted = norm
    return norm


def unmount() -> None:
    global _mounted  # noqa: PLW0603
    old = _mounted
    if not old:
        return
    reg.invalidate_fleet_cache()
    script = _stop_interface_script()
    if script is not None:
        try:
            subprocess.run(
                ["bash", str(script)],
                cwd=old,
                env=_workspace_subprocess_env(old),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
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
