#!/usr/bin/env python3
"""
Rename files by token replacement and update markdown references.

This script is designed to keep path naming consistent with placeholder
conventions (for example, TOKEN_SOURCE -> TOKEN_TARGET) while minimizing accidental edits:
- it only rewrites references for files that are actually renamed
- it supports a dry-run mode
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

# Same default as sanitize_context.py (paths relative to process cwd, usually repo root).
DEFAULT_MAPPING_PATH = Path("sun/runtime/security-map.json")


@dataclass(frozen=True)
class RenamePlan:
    old_abs: Path
    new_abs: Path
    old_rel_posix: str
    new_rel_posix: str
    old_name: str
    new_name: str


def _iter_files(target: Path) -> Iterable[Path]:
    if target.is_file():
        if ".git" not in target.parts:
            yield target
        return
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        yield path


def _load_rules_from_mapping(mapping_path: Path) -> List[Tuple[str, str]]:
    if not mapping_path.exists():
        return []
    with open(mapping_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return []

    rules: List[Tuple[str, str]] = []
    custom = data.get("CUSTOM", {})
    if isinstance(custom, dict):
        for old, new in custom.items():
            if isinstance(old, str) and isinstance(new, str) and old:
                rules.append((old, new))

    literal = data.get("literal_replacements", {})
    if isinstance(literal, dict):
        for old, new in literal.items():
            if isinstance(old, str) and isinstance(new, str) and old:
                rules.append((old, new))

    unique: dict[str, str] = {}
    for old, new in rules:
        unique[old] = new
    return sorted(unique.items(), key=lambda pair: len(pair[0]), reverse=True)


def _apply_rules_to_name(name: str, rules: Sequence[Tuple[str, str]]) -> str:
    out = name
    for old, new in rules:
        out = out.replace(old, new)
    return out


def _build_rename_plan(target: Path, root: Path, rules: Sequence[Tuple[str, str]]) -> List[RenamePlan]:
    plans: List[RenamePlan] = []
    for path in _iter_files(target):
        new_name = _apply_rules_to_name(path.name, rules)
        if new_name == path.name:
            continue
        new_abs = path.with_name(new_name)
        old_rel = path.relative_to(root).as_posix()
        new_rel = new_abs.relative_to(root).as_posix()
        plans.append(
            RenamePlan(
                old_abs=path,
                new_abs=new_abs,
                old_rel_posix=old_rel,
                new_rel_posix=new_rel,
                old_name=path.name,
                new_name=new_name,
            )
        )
    return sorted(plans, key=lambda p: len(p.old_rel_posix), reverse=True)


def _validate_plan(plans: List[RenamePlan]) -> None:
    targets = {}
    for plan in plans:
        key = str(plan.new_abs)
        if key in targets and targets[key] != str(plan.old_abs):
            raise ValueError(f"Rename collision: {targets[key]} and {plan.old_abs} -> {plan.new_abs}")
        targets[key] = str(plan.old_abs)

    for plan in plans:
        if plan.new_abs.exists() and plan.new_abs != plan.old_abs:
            raise ValueError(f"Target already exists: {plan.new_abs}")


def _replace_references(text: str, plans: List[RenamePlan]) -> str:
    out = text
    for plan in plans:
        out = out.replace(plan.old_rel_posix, plan.new_rel_posix)
    # Update basename references only when unambiguous.
    old_name_counts = {}
    for plan in plans:
        old_name_counts[plan.old_name] = old_name_counts.get(plan.old_name, 0) + 1
    for plan in plans:
        if old_name_counts[plan.old_name] == 1:
            out = out.replace(plan.old_name, plan.new_name)
    return out


def _rewrite_markdown_references(
    target: Path, root: Path, plans: List[RenamePlan], dry_run: bool
) -> int:
    modified = 0
    for path in _iter_files(target):
        if path.suffix.lower() != ".md":
            continue
        original = path.read_text(encoding="utf-8")
        updated = _replace_references(original, plans)
        if updated == original:
            continue
        modified += 1
        if not dry_run:
            path.write_text(updated, encoding="utf-8")
    return modified


def run(
    target: Path,
    dry_run: bool = True,
    old: str | None = None,
    new: str | None = None,
    mapping_path: Path | None = None,
    use_mapping: bool = False,
) -> tuple[int, int]:
    target = target.resolve()
    if not target.exists():
        raise ValueError(f"Target does not exist: {target}")
    root = target if target.is_dir() else target.parent

    rules: List[Tuple[str, str]] = []
    if use_mapping:
        resolved_mapping = mapping_path if mapping_path is not None else DEFAULT_MAPPING_PATH
        rules.extend(_load_rules_from_mapping(resolved_mapping))
    if old is not None or new is not None:
        if not old or not new:
            raise ValueError("Both --old and --new must be provided together.")
        rules.insert(0, (old, new))
    if not rules:
        raise ValueError(
            "No replacement rules provided. Use --use-mapping (optional --mapping PATH; "
            "default: sun/runtime/security-map.json) and/or --old/--new."
        )

    dedup: dict[str, str] = {}
    for src, dst in rules:
        dedup[src] = dst
    effective_rules = sorted(dedup.items(), key=lambda pair: len(pair[0]), reverse=True)

    plans = _build_rename_plan(target=target, root=root, rules=effective_rules)
    _validate_plan(plans)

    renamed = len(plans)
    if not dry_run:
        for plan in plans:
            plan.old_abs.rename(plan.new_abs)

    updated_docs = _rewrite_markdown_references(
        target=target, root=root, plans=plans, dry_run=dry_run
    )
    return renamed, updated_docs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rename tokenized filenames and update markdown references."
    )
    parser.add_argument(
        "target",
        help="Directory or single file to process.",
    )
    parser.add_argument("--old", default=None, help="Token to replace in filenames.")
    parser.add_argument("--new", default=None, help="Replacement token for filenames.")
    parser.add_argument(
        "--mapping",
        default=None,
        help="JSON with CUSTOM / literal_replacements (default with --use-mapping: "
        "sun/runtime/security-map.json).",
    )
    parser.add_argument(
        "--use-mapping",
        action="store_true",
        help="Load replacement rules from --mapping, or from the default file if --mapping is omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without writing changes.",
    )
    args = parser.parse_args()

    renamed, updated_docs = run(
        target=Path(args.target),
        old=args.old,
        new=args.new,
        dry_run=args.dry_run,
        mapping_path=Path(args.mapping) if args.mapping else None,
        use_mapping=args.use_mapping,
    )
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"[{mode}] renamed_files={renamed} updated_markdown_files={updated_docs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
