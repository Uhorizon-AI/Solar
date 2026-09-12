#!/usr/bin/env python3
"""Resolve Solar machine-state homes outside the workspace.

Two contracts, one rule: machine state never lives inside `sun/` or inside a
planet repository.

- Framework runtime: ``SOLAR_RUNTIME_ROOT`` or ``<app data>/Solar/runtime``.
- Planet state: ``<app data>/Solar/planets/<bucket>/<skill>``, where the bucket
  is assigned by the stable index at ``<app data>/Solar/planets/index.json``.

Identity is always computed on the *physical* resolved path (``expanduser`` +
``realpath``), never on the string received, so a workspace opened through a
symlink and the same workspace opened by its real path produce one identity.

There is no silent fallback to ``sun/runtime``. Callers that need the legacy
location must say so explicitly with an override.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_APP_SCRIPTS = _SCRIPTS.parent.parent / "solar-app" / "scripts"
if str(_APP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_APP_SCRIPTS))

try:  # solar-app owns the cross-platform app-data location
    from host_platform.paths import app_data_dir as _app_data_dir
except Exception:  # pragma: no cover - keeps the resolver usable standalone

    def _app_data_dir() -> Path:
        override = os.environ.get("SOLAR_APP_DATA", "").strip()
        if override:
            return Path(override).expanduser().resolve()
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support"
        if sys.platform == "win32":
            base = (
                os.environ.get("APPDATA")
                or os.environ.get("LOCALAPPDATA")
                or str(Path.home())
            )
            return Path(base).expanduser()
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        if xdg:
            return Path(xdg).expanduser().resolve()
        return Path.home() / ".local" / "share"


INDEX_VERSION = 1


def canonical(path: str | os.PathLike[str]) -> Path:
    """expanduser + realpath. Non-existing tails are kept verbatim."""
    return Path(path).expanduser().resolve()


def solar_global_dir() -> Path:
    """``<app data>/Solar`` — the single home for Solar machine state."""
    return canonical(_app_data_dir() / "Solar")


def runtime_root() -> Path:
    """Framework runtime root. Override with ``SOLAR_RUNTIME_ROOT``."""
    override = os.environ.get("SOLAR_RUNTIME_ROOT", "").strip()
    if override:
        return canonical(override)
    return solar_global_dir() / "runtime"


def runtime_dir(*parts: str, create: bool = False) -> Path:
    """A directory under the framework runtime root."""
    path = runtime_root().joinpath(*parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def planets_root() -> Path:
    return solar_global_dir() / "planets"


def planets_index_path() -> Path:
    return planets_root() / "index.json"


def planet_key(planet_path: str | os.PathLike[str]) -> str:
    """Stable identity of a planet: SHA-256 of its real path."""
    real = canonical(planet_path)
    return hashlib.sha256(str(real).encode("utf-8")).hexdigest()


def _read_index() -> dict:
    path = planets_index_path()
    if not path.exists():
        return {"version": INDEX_VERSION, "planets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": INDEX_VERSION, "planets": {}}
    if not isinstance(data, dict) or not isinstance(data.get("planets"), dict):
        return {"version": INDEX_VERSION, "planets": {}}
    data.setdefault("version", INDEX_VERSION)
    return data


def _write_index_atomic(data: dict) -> None:
    path = planets_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".index-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def planet_bucket(planet_path: str | os.PathLike[str], name: str | None = None) -> str:
    """Physical bucket for a planet, registering it on first sight.

    The first planet to claim a name keeps the readable name. A *physically
    different* planet with the same name gets ``<name>-<12 hash chars>``. Two
    paths that resolve to the same planet reuse the same bucket.
    """
    real = canonical(planet_path)
    key = planet_key(real)
    logical = name or real.name

    index = _read_index()
    entry = index["planets"].get(key)
    if entry and entry.get("bucket"):
        if entry.get("path") != str(real) or entry.get("name") != logical:
            entry["path"] = str(real)
            entry["name"] = logical
            _write_index_atomic(index)
        return str(entry["bucket"])

    taken = {str(v.get("bucket")) for v in index["planets"].values()}
    bucket = logical if logical not in taken else f"{logical}-{key[:12]}"
    index["planets"][key] = {"path": str(real), "name": logical, "bucket": bucket}
    _write_index_atomic(index)
    return bucket


def planet_state_dir(
    planet_path: str | os.PathLike[str],
    skill: str,
    *,
    name: str | None = None,
    create: bool = False,
) -> Path:
    """``<app data>/Solar/planets/<bucket>/<skill>`` — never inside the repo."""
    bucket = planet_bucket(planet_path, name)
    path = planets_root() / bucket / skill
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rt = sub.add_parser("runtime", help="print the framework runtime root or a subdir")
    p_rt.add_argument("parts", nargs="*")
    p_rt.add_argument("--create", action="store_true")

    p_pl = sub.add_parser("planet", help="print a planet skill state dir")
    p_pl.add_argument("planet_path")
    p_pl.add_argument("skill")
    p_pl.add_argument("--name")
    p_pl.add_argument("--create", action="store_true")

    p_bk = sub.add_parser("bucket", help="print the bucket assigned to a planet")
    p_bk.add_argument("planet_path")
    p_bk.add_argument("--name")

    sub.add_parser("index", help="print the planets index path")

    args = parser.parse_args(argv)
    if args.cmd == "runtime":
        print(runtime_dir(*args.parts, create=args.create))
    elif args.cmd == "planet":
        print(planet_state_dir(args.planet_path, args.skill, name=args.name, create=args.create))
    elif args.cmd == "bucket":
        print(planet_bucket(args.planet_path, args.name))
    elif args.cmd == "index":
        print(planets_index_path())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
