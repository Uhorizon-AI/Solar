#!/usr/bin/env python3
"""
Deterministic, regex-based context sanitizer for markdown/plain text.
Replaces common identifiers with stable placeholders within one run.
No external dependencies (stdlib only).
"""

from __future__ import annotations

import argparse
import json
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
DEFAULT_MAPPING_PATH = Path("sun/runtime/security-map.json")
# Matches placeholders like [EMAIL_001], [COM], [UH-NAME], [SIGN_DATE]
PLACEHOLDER_PATTERN = re.compile(r"\[([A-Z0-9][A-Z0-9_-]*)\]")
# Matches placeholders wrapped with 1+ backticks on both sides.
BACKTICKED_PLACEHOLDER_PATTERN = re.compile(r"`+\[([A-Z0-9][A-Z0-9_-]*)\]`+")


@dataclass(frozen=True)
class CustomLiteralRule:
    text: str
    placeholder: str
    case_sensitive: bool
    word_boundary: bool


@dataclass(frozen=True)
class CustomRegexRule:
    pattern: re.Pattern[str]
    placeholder: str

def _load_custom_rules_from_mapping(
    loaded_mapping: Dict[str, Dict[str, str]],
) -> Tuple[List[CustomLiteralRule], List[CustomRegexRule]]:
    if not isinstance(loaded_mapping, dict):
        return [], []

    literal_rules: List[CustomLiteralRule] = []
    regex_rules: List[CustomRegexRule] = []

    # New preferred format inside security-map.json:
    # {
    #   "CUSTOM": {
    #      "ASCENDION": "[COM_001]"
    #   }
    # }
    custom_inline = loaded_mapping.get("CUSTOM", {})
    if isinstance(custom_inline, dict):
        for text, placeholder in custom_inline.items():
            if not isinstance(text, str) or not isinstance(placeholder, str):
                continue
            literal_rules.append(
                CustomLiteralRule(
                    text=text,
                    placeholder=placeholder,
                    case_sensitive=False,
                    word_boundary=True,
                )
            )

    # Backward compatible format (if still present in mapping file).
    literal_section = loaded_mapping.get("literal_replacements", {})
    if isinstance(literal_section, dict):
        for text, placeholder in literal_section.items():
            if not isinstance(text, str) or not isinstance(placeholder, str):
                continue
            literal_rules.append(
                CustomLiteralRule(
                    text=text,
                    placeholder=placeholder,
                    case_sensitive=False,
                    word_boundary=True,
                )
            )
    elif isinstance(literal_section, list):
        for item in literal_section:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            placeholder = item.get("placeholder")
            if not isinstance(text, str) or not isinstance(placeholder, str):
                continue
            case_sensitive = bool(item.get("case_sensitive", False))
            word_boundary = bool(item.get("word_boundary", True))
            literal_rules.append(
                CustomLiteralRule(
                    text=text,
                    placeholder=placeholder,
                    case_sensitive=case_sensitive,
                    word_boundary=word_boundary,
                )
            )

    regex_section = loaded_mapping.get("regex_replacements", [])
    if isinstance(regex_section, list):
        for item in regex_section:
            if not isinstance(item, dict):
                continue
            raw_pattern = item.get("pattern")
            placeholder = item.get("placeholder")
            if not isinstance(raw_pattern, str) or not isinstance(placeholder, str):
                continue

            flags = 0
            raw_flags = item.get("flags", "")
            if isinstance(raw_flags, str):
                if "i" in raw_flags:
                    flags |= re.IGNORECASE
                if "m" in raw_flags:
                    flags |= re.MULTILINE
                if "s" in raw_flags:
                    flags |= re.DOTALL
            try:
                compiled = re.compile(raw_pattern, flags)
            except re.error:
                continue
            regex_rules.append(CustomRegexRule(pattern=compiled, placeholder=placeholder))

    return literal_rules, regex_rules


def _apply_custom_rules(
    text: str,
    literal_rules: List[CustomLiteralRule],
    regex_rules: List[CustomRegexRule],
) -> Tuple[str, Dict[str, Dict[str, str]], Dict[str, int]]:
    out = text
    mapping_updates: Dict[str, Dict[str, str]] = {}
    counts: Dict[str, int] = {}

    for rule in literal_rules:
        escaped = re.escape(rule.text)
        if rule.word_boundary:
            pattern_text = rf"\b{escaped}\b"
        else:
            pattern_text = escaped
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        pattern = re.compile(pattern_text, flags)
        out, replaced = pattern.subn(rule.placeholder, out)
        if replaced:
            key = f"CUSTOM_LITERAL:{rule.placeholder}"
            counts[key] = counts.get(key, 0) + replaced

    for rule in regex_rules:
        out, replaced = rule.pattern.subn(rule.placeholder, out)
        if replaced:
            key = f"CUSTOM_REGEX:{rule.placeholder}"
            counts[key] = counts.get(key, 0) + replaced

    return out, mapping_updates, counts


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


def sanitize(
    text: str,
    existing_mapping: Optional[Dict[str, Dict[str, str]]] = None,
    custom_literals: Optional[List[CustomLiteralRule]] = None,
    custom_regexes: Optional[List[CustomRegexRule]] = None,
) -> Tuple[str, Dict[str, Dict[str, str]], Dict[str, int]]:
    """
    Returns (new_text, mapping_by_type, counts_by_type).
    mapping_by_type: entity -> {normalized_value: placeholder}
    """
    sanitized_text = text
    custom_mapping_updates: Dict[str, Dict[str, str]] = {}
    custom_counts: Dict[str, int] = {}
    if custom_literals or custom_regexes:
        sanitized_text, custom_mapping_updates, custom_counts = _apply_custom_rules(
            text=sanitized_text,
            literal_rules=custom_literals or [],
            regex_rules=custom_regexes or [],
        )

    spans = _collect_spans(sanitized_text)
    per_type_maps: Dict[str, Dict[str, str]] = {
        k: dict(v)
        for k, v in (existing_mapping or {}).items()
        if isinstance(v, dict)
    }
    for s in SPECS:
        per_type_maps.setdefault(s.name, {})
    for typ, updates in custom_mapping_updates.items():
        per_type_maps.setdefault(typ, {})
        per_type_maps[typ].update(updates)

    counters: Dict[str, int] = {
        s.name: _next_counter_from_placeholders(s.name, per_type_maps[s.name]) for s in SPECS
    }
    counts: Dict[str, int] = {s.name: 0 for s in SPECS}
    counts.update(custom_counts)

    # Build replacements from end to start so indices stay valid
    out = sanitized_text
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


def _wrap_placeholders_for_markdown(text: str) -> str:
    """Render placeholders as inline code in an idempotent way."""
    # 1) Normalize already wrapped placeholders to exactly one backtick pair.
    normalized = BACKTICKED_PLACEHOLDER_PATTERN.sub(r"`[\1]`", text)
    # 2) Wrap only bare placeholders (not already adjacent to backticks).
    bare_pattern = re.compile(r"(?<!`)\[([A-Z0-9][A-Z0-9_-]*)\](?!`)")
    return bare_pattern.sub(r"`[\1]`", normalized)


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
        default=None,
        help="Output file path (if omitted and input is a file, overwrites input file).",
    )
    p.add_argument(
        "--report",
        "-r",
        default=None,
        help="Optional JSON path with mapping and counts (handle as sensitive).",
    )
    p.add_argument(
        "--markdown-placeholders",
        choices=["auto", "on", "off"],
        default="auto",
        help="Wrap placeholders with backticks in markdown outputs (default: auto).",
    )
    args = p.parse_args()


    if args.input == "-":
        data = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            data = f.read()

    mapping_file = DEFAULT_MAPPING_PATH
    existing_mapping: Dict[str, Dict[str, str]] = {}
    loaded_map_raw: Dict[str, Dict[str, str]] = {}
    if mapping_file.exists():
        with open(mapping_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                loaded_map_raw = loaded
                allowed_map_keys = {s.name for s in SPECS}
                allowed_map_keys.add("CUSTOM")
                existing_mapping = {
                    k: v
                    for k, v in loaded.items()
                    if isinstance(v, dict)
                    and k in allowed_map_keys
                }

    custom_literals, custom_regexes = _load_custom_rules_from_mapping(loaded_map_raw)
    new_text, mapping, counts = sanitize(
        data,
        existing_mapping=existing_mapping,
        custom_literals=custom_literals,
        custom_regexes=custom_regexes,
    )

    if args.output is not None:
        output_target = args.output
    elif args.input != "-":
        # Default behavior for file inputs: overwrite source file.
        output_target = args.input
    else:
        # stdin input defaults to stdout output.
        output_target = "-"

    use_markdown_wrapping = False
    if args.markdown_placeholders == "on":
        use_markdown_wrapping = True
    elif args.markdown_placeholders == "auto":
        if output_target != "-" and str(output_target).lower().endswith(".md"):
            use_markdown_wrapping = True
    if use_markdown_wrapping:
        new_text = _wrap_placeholders_for_markdown(new_text)

    if output_target == "-":
        sys.stdout.write(new_text)
    else:
        with open(output_target, "w", encoding="utf-8") as f:
            f.write(new_text)

    if args.report:
        payload = {
            "counts": counts,
            "mapping": {k: v for k, v in mapping.items() if v},
        }
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")

    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in mapping.items() if v}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
