"""Resolve Solar workspace roots (always runs resolve_solar_home.sh from cwd)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_RESOLVE_SCRIPT = Path(__file__).resolve().parent / "resolve_solar_home.sh"


def resolve_solar_home(*, force_home: str | None = None) -> tuple[Path, Path]:
    """Return (SOLAR_HOME, SOLAR_CORE_ROOT) as absolute Paths."""
    inner = f'source "{_RESOLVE_SCRIPT}" && solar_resolve_home --export'
    if force_home:
        inner += f' --home "{force_home}"'

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

    home_s = vals.get("SOLAR_HOME", "")
    core_s = vals.get("SOLAR_CORE_ROOT", "")
    if not home_s or not core_s:
        raise RuntimeError("resolver did not return SOLAR_HOME / SOLAR_CORE_ROOT")
    home = Path(home_s).resolve()
    core = Path(core_s).resolve()
    if not home.is_dir() or not core.is_dir():
        raise RuntimeError("resolved paths are not directories")
    os.environ["SOLAR_HOME"] = str(home)
    os.environ["SOLAR_CORE_ROOT"] = str(core)
    os.environ["REPO_ROOT"] = str(home)
    return home, core


def repo_root() -> Path:
    """REPO_ROOT alias (same as SOLAR_HOME)."""
    home, _ = resolve_solar_home()
    return home


def resolve_under_home(rel: str) -> Path:
    """Resolve a repo-relative path (legacy core/ prefix or sun/ paths)."""
    home, core = resolve_solar_home()
    p = Path(rel)
    if p.is_absolute():
        return p.resolve()
    text = str(rel)
    if text.startswith("core/"):
        return (core / text[len("core/") :]).resolve()
    return (home / text).resolve()


if __name__ == "__main__":
    try:
        h, c = resolve_solar_home()
        print(f"SOLAR_HOME={h}")
        print(f"SOLAR_CORE_ROOT={c}")
        print(f"REPO_ROOT={h}")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
