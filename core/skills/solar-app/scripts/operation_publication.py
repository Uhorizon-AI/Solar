"""Publication scoping shared by the console's read-only surfaces.

This module is deliberately feature-neutral: it holds the pieces that decide
*which* planets a read-only console surface may look at and how large a file it
may read. It used to live inside the report reader; the report concept is gone,
and the dashboard reader still needs exactly these four things, so they survive
here instead of being duplicated or lost.

It contains no report logic and no dashboard logic: no index parsing, no
confinement to a planet's `operations/`, no rendering, no routes. Keep it that
way; anything that only one surface needs belongs in that surface.
"""
import importlib.util
from pathlib import Path
import re

CLIENT = Path(__file__).resolve().parents[2] / 'solar-client/scripts'
INVENTORY = CLIENT / 'skill_inventory.py'

# Bounded read limit for any single published file the console reads.
MAX_INDEX = 128 * 1024
# Stable error code for an unreadable or invalid source, surfaced to the page.
INVALID_INDEX = 'index_unreadable'

NAME = re.compile(r'[a-zA-Z0-9_-]+\Z')

_inventory = None


class PublicationUnavailable(ValueError):
    """The client settings that scope publication could not be read."""


def excluded_planets(workspace):
    """Client planet exclusions, read without importing solar-client at module load."""
    global _inventory
    if _inventory is None:
        if not INVENTORY.is_file():
            raise PublicationUnavailable('Client skill inventory is unavailable')
        try:
            spec = importlib.util.spec_from_file_location('skill_inventory', INVENTORY)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # ImportError, SyntaxError, AttributeError, ...
            raise PublicationUnavailable('Client skill inventory could not be loaded') from exc
        _inventory = module
    try:
        return set(_inventory.settings(workspace).get('sync_exclude_planets', []))
    except ValueError as exc:
        raise PublicationUnavailable(str(exc))


def bounded_read(path, limit):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Published file exceeds size limit')
    return data


def published_planets(workspace):
    """Planets eligible for publication: named, inside planets/ and not excluded."""
    workspace = Path(workspace).resolve()
    excluded = excluded_planets(workspace)
    for planet in sorted((workspace / 'planets').glob('*')):
        if planet.name in excluded or not NAME.fullmatch(planet.name):
            continue
        if not planet.is_dir() or not planet.resolve().is_relative_to(workspace / 'planets'):
            continue
        yield planet
