#!/usr/bin/env python3
"""Atomically migrate gemini→agy in workspace .env priority keys.

Usage:
  python3 migrate_workspace_env_agy.py /path/to/workspace/.env

Exit 0: no-op or migrated OK.
Exit 1: read/write error.
Stdout: summary (before -> after | no-op).
Stderr: WARN for residual *_GEMINI_CMD keys (never renamed).
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

_PRIORITY_KEYS = (
    "SOLAR_ROUTER_PROVIDER_PRIORITY",
    "SOLAR_AI_PROVIDER_PRIORITY",
)
_GEMINI_CMD_KEYS = (
    "SOLAR_ROUTER_GEMINI_CMD",
    "SOLAR_AI_GEMINI_CMD",
)

_SCRIPTS_ROUTER = Path(__file__).resolve().parents[2] / "solar-router" / "scripts"
if str(_SCRIPTS_ROUTER) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROUTER))

from migrate_provider_priority import migrate_priority_csv  # noqa: E402

_ACTIVE_ASSIGN = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def migrate_env_text(text: str) -> tuple[str, list[tuple[str, str, str]], list[str]]:
    """Return (new_text, changes[(key, before, after)], gemini_cmd_keys_found)."""
    changes: list[tuple[str, str, str]] = []
    gemini_cmds: list[str] = []
    out: list[str] = []

    for body in text.splitlines():
        stripped = body.lstrip()
        if not stripped or stripped.startswith("#"):
            out.append(body)
            continue

        m = _ACTIVE_ASSIGN.match(body)
        if not m:
            out.append(body)
            continue

        lead, key, value = m.group(1), m.group(2), m.group(3)

        if key in _GEMINI_CMD_KEYS:
            gemini_cmds.append(key)
            out.append(f"{lead}{key}={value}")
            continue

        if key in _PRIORITY_KEYS:
            migrated, changed = migrate_priority_csv(value)
            if changed:
                changes.append((key, value, migrated))
                out.append(f"{lead}{key}={migrated}")
            else:
                out.append(f"{lead}{key}={value}")
            continue

        out.append(f"{lead}{key}={value}")

    new_text = "\n".join(out)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, changes, gemini_cmds


def migrate_workspace_env(env_path: Path) -> int:
    path = env_path.expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: .env not found: {path}", file=sys.stderr)
        return 1

    try:
        original = path.read_text(encoding="utf-8")
        mode = path.stat().st_mode
    except OSError as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        return 1

    new_text, changes, gemini_cmds = migrate_env_text(original)

    for key in gemini_cmds:
        print(
            f"WARN: remove {key}. "
            "Do not rename the value in place (e.g. gemini -y is invalid under AGY). "
            "Optional: SOLAR_ROUTER_AGY_CMD=agy -p --dangerously-skip-permissions",
            file=sys.stderr,
        )

    if not changes:
        print("no-op")
        return 0

    parent = path.parent
    fd = None
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".env.agy.", dir=str(parent), text=True)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
            fd = None
            tmp.write(new_text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, mode & 0o7777)
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError as exc:
        print(f"ERROR: cannot write {path}: {exc}", file=sys.stderr)
        return 1
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_name is not None and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    for key, before, after in changes:
        print(f"{key}: {before} -> {after}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print("Usage: migrate_workspace_env_agy.py <workspace/.env>", file=sys.stderr)
        return 2
    return migrate_workspace_env(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
