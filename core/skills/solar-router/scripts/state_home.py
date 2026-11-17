"""Resolve the official state home of a skill for an unattended task (issue #175).

A task that names a skill in `state_home` may write to `<app data>/Solar/planets/<bucket>/<skill>/`
and nowhere else outside the workspace. Two things must agree before that folder is opened:

- the task declares `state_home: <skill>` (part of what the user approved), and
- the skill's own SKILL.md declares `state_home: true` (the skill opted in).

There is no fallback: if the folder cannot be resolved or created, the task fails with
`state_home_unavailable` instead of writing somewhere else (`core/docs/state-homes.md`).
"""
from __future__ import annotations

import pathlib
import re
import sys

_PATHS_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))

import solar_runtime  # noqa: E402


class StateHomeError(RuntimeError):
    """A task's state home cannot be granted. `code` is the error code the worker and router report.

    Defined here, not in `providers`: the worker needs it without importing the providers, which
    resolve the workspace as soon as they are imported.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _check_name(kind: str, value: str) -> str:
    value = (value or "").strip()
    if not _NAME.fullmatch(value) or value in (".", "..") or ".." in value:
        raise StateHomeError("state_home_invalid", f"{kind} {value!r} is not a plain name")
    return value


def skill_declares_state_home(skill_md: pathlib.Path) -> bool:
    """True when the SKILL.md frontmatter has a scalar `state_home: true`."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---", 4)
    if end < 0:
        return False
    for line in text[4:end].splitlines():
        match = re.match(r"^state_home:\s*(.*?)\s*$", line)
        if match:
            return match.group(1).strip("'\"").lower() == "true"
    return False


def resolve_state_home(workspace: pathlib.Path, planet: str, skill: str) -> pathlib.Path:
    """Create and return `<app data>/Solar/planets/<bucket>/<skill>` for a planet skill that opted in.

    Raises StateHomeError (`state_home_invalid`, `state_home_not_declared`, `state_home_unavailable`).
    """
    planet = _check_name("planet", planet)
    skill = _check_name("skill", skill)
    planets = (pathlib.Path(workspace) / "planets").resolve()
    planet_dir = (planets / planet).resolve()
    if planet_dir.parent != planets or not planet_dir.is_dir():
        raise StateHomeError("state_home_invalid", f"planet {planet!r} is not a planet of this workspace")
    matches = [m for m in planet_dir.glob(f"**/skills/{skill}/SKILL.md")]
    if len(matches) != 1:
        raise StateHomeError("state_home_invalid",
                             f"skill {skill!r} not found exactly once in planet {planet!r}")
    if not skill_declares_state_home(matches[0]):
        raise StateHomeError("state_home_not_declared",
                             f"skill {skill!r} does not declare `state_home: true` in its SKILL.md")
    outside = StateHomeError("state_home_unavailable",
                             f"state home of {skill!r} resolved outside its official location")
    try:
        root = solar_runtime.planets_root().resolve()
        # Validate the resolved location first: a rejected request must leave nothing on disk.
        home = solar_runtime.planet_state_dir(planet_dir, skill, create=False).resolve()
        if home.name != skill or home.parent.parent != root:
            raise outside
        home.mkdir(parents=True, exist_ok=True)
        home = home.resolve(strict=True)
    except StateHomeError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise StateHomeError("state_home_unavailable", f"cannot create the state home of {skill!r}: {exc}") from exc
    if home.name != skill or home.parent.parent != root or not home.is_dir():
        raise outside
    return home
