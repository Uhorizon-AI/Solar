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


def entries() -> dict:
    workspace, install = resolve_solar_paths()
    # Discovery reads live eligible sources. No runtime initialization or writes.
    return inventory(workspace, install / "core")


def search(query: str, limit: int = 5, preferred_namespace: str = "") -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise ValueError("query must contain 1 to 512 characters")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer from 1 to 10")
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
                         description=entry["description"][:400], revision=entry["revision"],
                         matches=matched[:10], dependency_availability="unknown")
        if len(json.dumps(dict(results=results + [candidate]), indent=2, sort_keys=True).encode()) > 7900:
            truncated = True
            break
        results.append(candidate)
    return dict(results=results, truncated=truncated)


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
