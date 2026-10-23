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
    workspace; it wins there because it is the most specific."""
    if any(is_inside(path, root, case_insensitive) for root in installation_roots):
        return INSTALLATION
    if any(is_inside(path, root, case_insensitive) for root in planet_roots):
        return PLANET
    if is_inside(path, workspace, case_insensitive):
        return WORKSPACE
    return OUTSIDE


def aggregate_zone(zones: Iterable[str]) -> str:
    """The outermost zone of a task. No paths: the workspace (the default of a read without paths)."""
    ranks = [ZONES.index(z) for z in zones]
    return ZONES[max(ranks)] if ranks else WORKSPACE


def describe(paths: Iterable[str], **roots) -> dict:
    """Aggregate zone plus the path -> zone list the approval text shows."""
    listed = [(path, zone_of(path, **roots)) for path in paths]
    return {"zone": aggregate_zone(z for _, z in listed), "paths": listed}


def physically_inside_workspace(path: str, workspace: str, case_insensitive: Optional[bool] = None) -> bool:
    """Impact is decided by physical containment, not by the zone's name: the global installation is
    outside the workspace even though its zone is `installation`; the copy inside a planet is inside."""
    return is_inside(path, workspace, case_insensitive)
