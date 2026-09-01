#!/usr/bin/env python3
"""Migrate SOLAR_ROUTER_PROVIDER_PRIORITY CSV tokens (gemini → agy).

Usage:
  python3 migrate_provider_priority.py 'gemini,codex'
  echo 'GEMINI,codex' | python3 migrate_provider_priority.py

Stdout: migrated CSV (+ trailing newline). Exit 0 when parseable.
"""
from __future__ import annotations

import sys

_LEGACY_TO_CANONICAL = {
    "gemini": "agy",
}


def migrate_priority_csv(raw: str) -> tuple[str, bool]:
    """Return (migrated_csv, changed).

    - casefold tokens
    - map legacy gemini → agy
    - dedupe preserving order
    - strip empties / whitespace
    """
    naive: list[str] = []
    naive_seen: set[str] = set()
    for part in (raw or "").split(","):
        token = part.strip().casefold()
        if not token or token in naive_seen:
            continue
        naive_seen.add(token)
        naive.append(token)

    out: list[str] = []
    seen: set[str] = set()
    for token in naive:
        canonical = _LEGACY_TO_CANONICAL.get(token, token)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)

    migrated = ",".join(out)
    changed = migrated != ",".join(naive)
    return migrated, changed


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        raw = " ".join(argv[1:])
    else:
        raw = sys.stdin.read()
    migrated, _changed = migrate_priority_csv(raw)
    sys.stdout.write(migrated + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
