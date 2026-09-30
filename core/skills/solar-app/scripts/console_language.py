"""The only table of console language tokens.

English is the effective language unless the value is Spanish.
Writers store ``en`` or ``es``. ``solar client language`` and the console
both call this module.
"""
from __future__ import annotations

import sys

_SPANISH = frozenset({"es", "es-es", "spanish"})
_ENGLISH = frozenset({"en", "en-us", "en-gb", "english"})


def normalize_token(value) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def canonical_language(value) -> str | None:
    """``en`` or ``es`` when the token is accepted, otherwise ``None``."""
    token = normalize_token(value)
    if token in _ENGLISH:
        return "en"
    if token in _SPANISH:
        return "es"
    return None


def effective_language(value) -> str:
    """What the console shows. Unknown and missing values are English."""
    return "es" if normalize_token(value) in _SPANISH else "en"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"effective", "canonical"}:
        sys.stderr.write("usage: console_language.py effective|canonical VALUE\n")
        return 2
    if argv[1] == "effective":
        print(effective_language(argv[2]))
        return 0
    language = canonical_language(argv[2])
    if language is None:
        sys.stderr.write(
            "ERROR: language must be en or es"
            " (aliases: english, es-ES, es_ES, spanish)\n"
        )
        return 2
    print(language)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
