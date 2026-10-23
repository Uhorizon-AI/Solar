"""Which zone a declared path falls in: installation, planet, workspace or outside.

Zones are *declared, not verified*: they classify what a harness says a task touches. They do not
confine the client. Pure functions; the caller supplies the roots (nothing here reads the environment).

Order, from the inside out: installation, planet, workspace, outside. A path takes its most specific
zone; a task with several paths takes the outermost one (`aggregate_zone`).
"""
from __future__ import annotations

import os
import sys
from typing import Iterable, Optional

INSTALLATION, PLANET, WORKSPACE, OUTSIDE = "installation", "planet", "workspace", "outside"
ZONES = (INSTALLATION, PLANET, WORKSPACE, OUTSIDE)


def resolve(path: str, case_insensitive: Optional[bool] = None) -> str:
    """Real path (symlinks, `..`), comparable. A target that does not exist yet resolves through its
    nearest existing ancestor. Case-folded where the filesystem is case-insensitive (macOS)."""
    if case_insensitive is None:
        case_insensitive = sys.platform == "darwin"
    real = os.path.realpath(os.path.expanduser(path))
    return real.casefold() if case_insensitive else real


def is_inside(path: str, root: str, case_insensitive: Optional[bool] = None) -> bool:
    """True when `path` is `root` or below it, by whole directory components (not a text prefix)."""
    p, r = resolve(path, case_insensitive), resolve(root, case_insensitive)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def zone_of(path: str, *, workspace: str, installation_roots: Iterable[str] = (),
            planet_roots: Iterable[str] = (), case_insensitive: Optional[bool] = None) -> str:
    """The most specific zone of one path. `planet_roots` are the configured planets of the
    workspace, not any folder called `planets`. The installation can sit inside a planet inside the
    workspace; it wins there because it is the most specific. A planet counts only while it is
    physically inside the workspace (a planet linked to a folder outside is `outside`)."""
    if any(is_inside(path, root, case_insensitive) for root in installation_roots):
        return INSTALLATION
    if not is_inside(path, workspace, case_insensitive):
        return OUTSIDE
    if any(is_inside(path, root, case_insensitive) for root in planet_roots):
        return PLANET
    return WORKSPACE


def aggregate_zone(zones: Iterable[str]) -> str:
    """The outermost zone of a task. No paths: the workspace (the default of a read without paths)."""
    ranks = [ZONES.index(z) for z in zones]
    return ZONES[max(ranks)] if ranks else WORKSPACE


def describe(paths: Iterable[str], **roots) -> dict:
    """Aggregate zone plus the path -> zone list the approval text shows. The aggregate is the outermost
    zone, and `outside` as soon as any path is physically outside the workspace, even one whose own zone
    is `installation` (the global installation): that is what decides the wait."""
    listed = [(path, zone_of(path, **roots)) for path in paths]
    aggregate = aggregate_zone(z for _, z in listed)
    case = roots.get("case_insensitive")
    if any(not is_inside(path, roots["workspace"], case) for path, _ in listed):
        aggregate = OUTSIDE
    return {"zone": aggregate, "paths": listed}


def physically_inside_workspace(path: str, workspace: str, case_insensitive: Optional[bool] = None) -> bool:
    """Impact is decided by physical containment, not by the zone's name: the global installation is
    outside the workspace even though its zone is `installation`; the copy inside a planet is inside."""
    return is_inside(path, workspace, case_insensitive)


def roots_for(workspace: str, solar_root: Optional[str]) -> dict:
    """The roots `zone_of` needs for one workspace: the global installation, the copy of the framework
    inside the `solar` planet, and the configured planets (the folders directly under `planets/`)."""
    planets_dir = os.path.join(workspace, "planets")
    try:
        planets = sorted(os.path.join(planets_dir, name) for name in os.listdir(planets_dir)
                         if not name.startswith(".") and os.path.isdir(os.path.join(planets_dir, name)))
    except OSError:
        planets = []
    installs = [os.path.join(planets_dir, "solar", "core")]
    if solar_root:
        installs.append(solar_root)
    return dict(workspace=workspace, installation_roots=installs, planet_roots=planets)


def declared_paths(access_scopes: Iterable[str], folder: Optional[str], workspace: str) -> list:
    """What a task declares it touches: its access paths, else the folder it starts in, else the workspace."""
    scopes = list(access_scopes)
    return scopes or [folder or workspace]


def report(paths: Iterable[str], workspace: str, solar_root: Optional[str]) -> dict:
    """Aggregate zone and path -> zone list, always labelled as declared and not verified."""
    got = describe(list(paths), **roots_for(workspace, solar_root))
    return dict(zone=got["zone"], paths=[dict(path=p, zone=zn) for p, zn in got["paths"]],
                verified=False, note="declared, not verified")
