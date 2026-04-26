#!/usr/bin/env python3
"""
Deterministic, regex-based context sanitizer for markdown/plain text.
Replaces common identifiers with stable placeholders within one run.
No external dependencies (stdlib only).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PatternSpec:
    name: str
    pattern: re.Pattern[str]
    normalize: Callable[[str], str]


def _build_specs() -> List[PatternSpec]:
    # Order matters for overlap resolution: longer / more specific first where possible.
    iban_intl = re.compile(
        r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"
        r"|\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b",
        re.IGNORECASE,
    )
    email = re.compile(
        r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    )
    url = re.compile(
        r"https?://[^\s\)\]<>\"']+",
        re.IGNORECASE,
    )
    # International phone (conservative): requires '+' and 8-15 digits with common separators.
    phone_intl = re.compile(
        r"(?<!\w)\+\s*(?:[0-9][\s().-]*){7,15}[0-9](?!\w)",
    )

    def norm_email(s: str) -> str:
        return s.strip().lower()

    def norm_iban(s: str) -> str:
        return re.sub(r"\s+", "", s).upper()

    def norm_phone(s: str) -> str:
        return re.sub(r"\D", "", s)

    def norm_url(s: str) -> str:
        return s.strip()

    return [
        PatternSpec("IBAN_INTL", iban_intl, norm_iban),
        PatternSpec("EMAIL", email, norm_email),
        PatternSpec("URL", url, norm_url),
        PatternSpec("PHONE_INTL", phone_intl, norm_phone),
    ]


SPECS: List[PatternSpec] = _build_specs()


def _next_counter_from_placeholders(entity_type: str, pmap: Dict[str, str]) -> int:
    max_idx = 0
    pattern = re.compile(rf"\[{re.escape(entity_type)}_(\d+)\]$")
    for placeholder in pmap.values():
        match = pattern.match(placeholder)
        if not match:
            continue
        idx = int(match.group(1))
        if idx > max_idx:
            max_idx = idx
    return max_idx


def _collect_spans(text: str) -> List[Tuple[int, int, str, str]]:
    """Return non-overlapping spans (start, end, type, raw) priority by (start, -len, order)."""
    raw_hits: List[Tuple[int, int, str, str, int]] = []
    for priority, spec in enumerate(SPECS):
        for m in spec.pattern.finditer(text):
            raw = m.group(0)
            raw_hits.append((m.start(), m.end(), spec.name, raw, priority))
    raw_hits.sort(key=lambda t: (t[0], -(t[1] - t[0]), t[4]))
    kept: List[Tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, name, raw, _prio in raw_hits:
        if start < last_end:
            continue
        kept.append((start, end, name, raw))
        last_end = end
    return kept


def _planet_mapping_path(planet: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", planet):
        raise ValueError(f"Invalid planet name: {planet!r}")
    return Path("planets") / planet / ".solar" / "security" / "placeholders.json"


def sanitize(
    text: str,
    existing_mapping: Optional[Dict[str, Dict[str, str]]] = None,
) -> Tuple[str, Dict[str, Dict[str, str]], Dict[str, int]]:
    """
    Returns (new_text, mapping_by_type, counts_by_type).
    mapping_by_type: entity -> {normalized_value: placeholder}
    """
    spans = _collect_spans(text)
    per_type_maps: Dict[str, Dict[str, str]] = {
        s.name: dict((existing_mapping or {}).get(s.name, {})) for s in SPECS
    }
    counters: Dict[str, int] = {
        s.name: _next_counter_from_placeholders(s.name, per_type_maps[s.name]) for s in SPECS
    }
    counts: Dict[str, int] = {s.name: 0 for s in SPECS}

    # Build replacements from end to start so indices stay valid
    out = text
    for start, end, typ, raw in reversed(spans):
        spec = next(s for s in SPECS if s.name == typ)
        key = spec.normalize(raw)
        pmap = per_type_maps[typ]
        if key not in pmap:
            counters[typ] += 1
            pmap[key] = f"[{typ}_{counters[typ]:03d}]"
        placeholder = pmap[key]
        out = out[:start] + placeholder + out[end:]
        counts[typ] += 1

    # counts reflect number of spans replaced; unique keys per type in pmap
    return out, per_type_maps, counts


def main() -> int:
    p = argparse.ArgumentParser(
        description="Sanitize markdown/plain text for safer AI context (regex V1)."
    )
    p.add_argument(
        "--input",
        "-i",
        default="-",
        help="Input file path, or '-' for stdin (default).",
    )
    p.add_argument(
        "--output",
        "-o",
        default="-",
        help="Output file path, or '-' for stdout (default).",
    )
    p.add_argument(
        "--report",
        "-r",
        default=None,
        help="Optional JSON path with mapping and counts (handle as sensitive).",
    )
    p.add_argument(
        "--planet",
        default=None,
        help=(
            "Planet name used to persist placeholder mappings automatically at "
            "planets/<planet>/.solar/security/placeholders.json"
        ),
    )
    args = p.parse_args()

    if args.input == "-":
        data = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            data = f.read()

    mapping_file: Optional[Path] = None
    if args.planet:
        mapping_file = _planet_mapping_path(args.planet)

    existing_mapping: Dict[str, Dict[str, str]] = {}
    if mapping_file and mapping_file.exists():
        with open(mapping_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                existing_mapping = {
                    k: v for k, v in loaded.items() if isinstance(v, dict)
                }

    new_text, mapping, counts = sanitize(data, existing_mapping=existing_mapping)

    if args.output == "-":
        sys.stdout.write(new_text)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(new_text)

    if args.report:
        payload = {
            "counts": counts,
            "mapping": {k: v for k, v in mapping.items() if v},
        }
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")

    if mapping_file:
        mapping_file.parent.mkdir(parents=True, exist_ok=True)
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in mapping.items() if v}, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
