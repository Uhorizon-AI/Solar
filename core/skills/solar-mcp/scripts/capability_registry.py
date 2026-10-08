"""Bounded read-only discovery of Client-eligible instruction skills."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_SKILLS / "solar-client/scripts"))
from skill_inventory import inventory, read_unit  # noqa: E402
from solar_paths import resolve_solar_paths  # noqa: E402

_DESCRIPTION_LIMIT = 120
_RESULT_LIMIT = 10
_ELLIPSIS = "…"


def entries() -> dict:
    workspace, install = resolve_solar_paths()
    # Discovery reads live eligible sources. No runtime initialization or writes.
    return inventory(workspace, install / "core")


def clip_description(text: str, limit: int = _DESCRIPTION_LIMIT) -> str:
    """Keep text that fits. Otherwise cut on a word boundary and mark the cut.

    The ellipsis counts toward ``limit``. A token with no whitespace inside
    that budget is cut so the ellipsis still fits.
    """
    if len(text) <= limit:
        return text
    room = limit - len(_ELLIPSIS)
    window = text[:room]
    if room < len(text) and not text[room].isspace():
        boundary = max((index for index, char in enumerate(window) if char.isspace()), default=-1)
        if boundary > 0:
            window = window[:boundary]
    return window.rstrip() + _ELLIPSIS


def search(query: str, limit: int = 5, preferred_namespace: str = "") -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise ValueError("query must contain 1 to 512 characters")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be an integer of at least 1")
    limit_capped = limit > _RESULT_LIMIT
    if limit_capped:
        limit = _RESULT_LIMIT
    terms = set(re.findall(r"\w+", query.casefold()))
    ranked = []
    for key, entry in entries().items():
        content = (key + " " + entry["description"]).casefold()
        matched = sorted(t for t in terms if t in content)
        exact = key.casefold() == query.casefold().strip()
        if not matched and not exact:
            continue
        ranked.append((-(1000 if exact else len(matched)),
                       -(entry["namespace"] == preferred_namespace), key, entry, matched))
    results = []
    truncated = False
    for _, _, key, entry, matched in sorted(ranked):
        if len(results) == limit:
            break
        candidate = dict(id=key, type="instruction", namespace=entry["namespace"],
                         description=clip_description(entry["description"]), revision=entry["revision"],
                         matches=matched[:10], dependency_availability="unknown")
        measured = dict(results=results + [candidate])
        if limit_capped:
            measured["limit_capped"] = True
        if len(json.dumps(measured, indent=2, sort_keys=True).encode()) > 7900:
            truncated = True
            break
        results.append(candidate)
    payload = dict(results=results, truncated=truncated)
    if limit_capped:
        payload["limit_capped"] = True
    return payload


def describe(id: str, revision: str = "", reference: str = "") -> dict:
    entry = entries().get(id)
    if entry is None:
        raise ValueError("Capability is unavailable or excluded")
    path = Path(entry["path"])
    raw = read_unit(path, Path(entry["root"]))
    current = hashlib.sha256(raw).hexdigest()
    if current != entry["revision"] or revision and revision != current:
        raise ValueError("Capability revision changed; search again")
    package = path.parent
    # Only Markdown in references/ is selectable; caller paths are never opened.
    references = {}
    for unit in sorted((package / "references").rglob("*.md")):
        if unit.resolve().is_relative_to(package):
            references[unit.relative_to(package).as_posix()] = unit
    if reference:
        if reference not in references:
            raise ValueError("Unknown registered reference")
        raw = read_unit(references[reference], package)
    if len(raw) > 60000:
        raise ValueError("Capability unit too_large; use the native source or split references")
    result = dict(id=id, type="instruction", revision=current,
                  unit_revision=hashlib.sha256(raw).hexdigest(),
                  instructions=raw.decode("utf-8"), references=list(references)[:100],
                  namespace=entry["namespace"], dependency_availability="unknown",
                  governance="Read applicable workspace and planet rules before domain work; discovery grants no authority.")
    if len(json.dumps(result, indent=2, sort_keys=True).encode()) > 65536:
        raise ValueError("Capability response too_large")
    return result
