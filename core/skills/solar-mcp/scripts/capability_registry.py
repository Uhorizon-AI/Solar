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
_OUTLINE_ABOVE = 4096
_OUTLINE_RATIO_PERCENT = 85
_GOVERNANCE_MARKERS = (
    "authority", "gate", "governance", "safety", "never", "approval",
    "autoridad", "gobernanza", "seguridad", "nunca", "aprobaci", "obligatori",
    "prohib", "regla", "límite", "limite", "dependencia", "antes de",
)
_HEADING = re.compile(r"^(#{2,3})[ \t]+(\S.*?)\s*$")
_TRAILING_HASHES = re.compile(r"\s+#+\s*$")
_GOVERNANCE_NOTE = (
    "Read applicable workspace and planet rules before domain work; "
    "discovery grants no authority."
)


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


def _heading_title(raw: str) -> str:
    return _TRAILING_HASHES.sub("", raw).strip()


def _is_governance(title: str) -> bool:
    folded = title.casefold()
    return any(marker in folded for marker in _GOVERNANCE_MARKERS)


def _fence_mark(bare: str):
    """Return the fence character, its length, and the rest of the line.

    A fence is a line of at least three backticks or tildes, indented by at
    most three spaces. Four spaces, or a tab, is an indented code line.
    """
    indent = len(bare) - len(bare.lstrip(" "))
    if indent > 3 or bare[indent:indent + 1] == "\t":
        return None
    stripped = bare[indent:]
    if stripped[:1] not in ("`", "~"):
        return None
    char = stripped[0]
    length = 0
    for item in stripped:
        if item != char:
            break
        length += 1
    if length < 3:
        return None
    return char, length, stripped[length:]


def _sections(text: str) -> list[dict]:
    """Level-2 and level-3 slices of the original text, in document order.

    A section starts at its heading and runs until the next heading of the
    same or higher level. Headings inside fenced code blocks are ignored.
    A fence is indented by at most three spaces and closes only on the same
    character, repeated at least as many times as the opening line, with
    nothing else on that line.
    """
    found = []
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        mark = _fence_mark(bare)
        if fence is None:
            # A backtick run whose remainder contains a backtick is inline code,
            # not an opening fence.
            if mark is not None and not (mark[0] == "`" and "`" in mark[2]):
                fence = (mark[0], mark[1])
            else:
                match = _HEADING.match(bare)
                if match:
                    found.append((offset, len(match.group(1)), _heading_title(match.group(2))))
        elif mark is not None and mark[0] == fence[0] and mark[1] >= fence[1] and not mark[2].strip():
            fence = None
        offset += len(line)
    sections = []
    for index, (start, level, title) in enumerate(found):
        end = len(text)
        for later_start, later_level, _title in found[index + 1:]:
            if later_level <= level:
                end = later_start
                break
        chunk = text[start:end]
        sections.append(dict(title=title, level=level, start=start,
                             bytes=len(chunk.encode("utf-8")), text=chunk))
    return sections


def _preamble(text: str, sections: list[dict]) -> str:
    """Original text after the frontmatter and before the first level-2 heading.

    The slice is not trimmed. A unit with no level-2 heading yields the whole
    body. Missing frontmatter starts the slice at the beginning of the unit.
    """
    start = 0
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            line_end = text.find("\n", end + 1)
            start = len(text) if line_end < 0 else line_end + 1
    first_h2 = next((item["start"] for item in sections if item["level"] == 2), None)
    if first_h2 is None or first_h2 < start:
        return text[start:]
    return text[start:first_h2]


def _reject_reference_path(value: str) -> None:
    if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/"):
        raise ValueError("reference does not accept a path")


def _reject_section_path(value: str) -> None:
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError("section does not accept a path")


def _response_bytes(result: dict) -> int:
    return len(json.dumps(result, indent=2, sort_keys=True).encode())


def _finish(result: dict) -> dict:
    if _response_bytes(result) > 65536:
        raise ValueError("Capability response too_large")
    return result


def _outline_is_smaller(outline: dict, complete: dict) -> bool:
    """True when the outline JSON is strictly under 85% of the complete body."""
    return _response_bytes(outline) * 100 < _response_bytes(complete) * _OUTLINE_RATIO_PERCENT


def describe(id: str, revision: str = "", reference: str = "", section: str = "", full: bool = False) -> dict:
    if type(full) is not bool:
        raise ValueError("full must be a boolean")
    if section and full:
        raise ValueError("section and full cannot be combined")
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
        _reject_reference_path(reference)
        if reference not in references:
            raise ValueError("Unknown registered reference")
        raw = read_unit(references[reference], package)
    if len(raw) > 60000:
        raise ValueError("Capability unit too_large; use the native source or split references")
    text = raw.decode("utf-8")
    listed = list(references)[:100]
    base = dict(id=id, type="instruction", revision=current, references=listed,
                namespace=entry["namespace"], dependency_availability="unknown",
                governance=_GOVERNANCE_NOTE)
    if section:
        _reject_section_path(section)
        parsed = _sections(text)
        chosen = next((item for item in parsed if item["title"] == section), None)
        if chosen is None:
            titles = ", ".join(item["title"] for item in parsed) or "(none)"
            raise ValueError(f"Unknown section. Titles: {titles}")
        return _finish(dict(base, section=section, instructions=chosen["text"],
                            unit_revision=hashlib.sha256(chosen["text"].encode("utf-8")).hexdigest()))
    complete = dict(base, instructions=text, unit_revision=hashlib.sha256(raw).hexdigest())
    if full or len(raw) <= _OUTLINE_ABOVE:
        return _finish(complete)
    parsed = _sections(text)
    governance = [item for item in parsed if _is_governance(item["title"])]
    outline = dict(
        base, description=entry["description"], outline=True,
        unit_revision=complete["unit_revision"],
        preamble=_preamble(text, parsed),
        sections=[dict(title=item["title"], level=item["level"], bytes=item["bytes"])
                  for item in parsed],
        governance_sections=[dict(title=item["title"], level=item["level"],
                                  bytes=item["bytes"], text=item["text"])
                             for item in governance])
    if not _outline_is_smaller(outline, complete):
        return _finish(complete)
    return _finish(outline)
