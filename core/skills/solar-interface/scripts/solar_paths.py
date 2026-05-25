"""Resolve Solar workspace + install roots (runs resolve_solar_paths.sh from cwd)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_RESOLVE_SCRIPT = Path(__file__).resolve().parent / "resolve_solar_paths.sh"


def resolve_solar_paths(*, force_workspace: str | None = None) -> tuple[Path, Path]:
    """Return (SOLAR_WORKSPACE, SOLAR_ROOT) as absolute Paths. SOLAR_ROOT contains core/."""
    inner = f'source "{_RESOLVE_SCRIPT}" && solar_resolve_paths --export'
    if force_workspace:
        inner += f' --workspace "{force_workspace}"'

    proc = subprocess.run(
        ["bash", "-c", inner],
        cwd=os.getcwd(),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "resolve failed").strip()
        raise RuntimeError(msg)

    vals: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            vals[key.strip()] = value.strip()

    workspace_s = vals.get("SOLAR_WORKSPACE", "")
    root_s = vals.get("SOLAR_ROOT", "")
    if not workspace_s or not root_s:
        raise RuntimeError("resolver did not return SOLAR_WORKSPACE / SOLAR_ROOT")
    workspace = Path(workspace_s).resolve()
    install_root = Path(root_s).resolve()
    if not workspace.is_dir() or not install_root.is_dir():
        raise RuntimeError("resolved paths are not directories")
    os.environ["SOLAR_WORKSPACE"] = str(workspace)
    os.environ["SOLAR_ROOT"] = str(install_root)
    return workspace, install_root


def solar_core_path() -> Path:
    """$SOLAR_ROOT/core"""
    _, root = resolve_solar_paths()
    return root / "core"


def workspace_root() -> Path:
    """Active agent workspace."""
    ws, _ = resolve_solar_paths()
    return ws


def resolve_under_home(rel: str) -> Path:
    """Resolve paths under workspace or under core/ (install)."""
    workspace, install_root = resolve_solar_paths()
    p = Path(rel)
    if p.is_absolute():
        return p.resolve()
    text = str(rel)
    if text.startswith("core/"):
        return (install_root / text).resolve()
    return (workspace / text).resolve()


if __name__ == "__main__":
    try:
        ws, root = resolve_solar_paths()
        print(f"SOLAR_WORKSPACE={ws}")
        print(f"SOLAR_ROOT={root}")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
