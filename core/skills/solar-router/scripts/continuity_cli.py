#!/usr/bin/env python3
"""CLI for sun/runtime/continuity/active.json."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_CLIENT = _SCRIPTS.parent.parent / "solar-client" / "scripts"
if str(_CLIENT) not in sys.path:
    sys.path.insert(0, str(_CLIENT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from solar_paths import resolve_solar_paths  # noqa: E402

SOLAR_WORKSPACE, _ = resolve_solar_paths()
ACTIVE = SOLAR_WORKSPACE / "sun" / "runtime" / "continuity" / "active.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty() -> dict:
    return {
        "intention_id": str(uuid.uuid4()),
        "active_task": "",
        "decisions": [],
        "completed_actions": [],
        "pending": [],
        "constraints": [],
        "next_owner": "",
        "updated_at": utc_now(),
        "channels_seen": [],
    }


def load() -> dict:
    if not ACTIVE.exists():
        return empty()
    try:
        data = json.loads(ACTIVE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty()
    return data if isinstance(data, dict) else empty()


def save(data: dict) -> None:
    data["updated_at"] = utc_now()
    ACTIVE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_status(_: argparse.Namespace) -> int:
    data = load()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    data = load()
    if not data.get("intention_id"):
        data["intention_id"] = str(uuid.uuid4())
    if args.task is not None:
        data["active_task"] = args.task
    if args.owner is not None:
        data["next_owner"] = args.owner
    if args.channel:
        seen = data.get("channels_seen") if isinstance(data.get("channels_seen"), list) else []
        if args.channel not in seen:
            seen.append(args.channel)
        data["channels_seen"] = seen[-12:]
    for field, values in (
        ("pending", args.pending),
        ("decisions", args.decision),
        ("completed_actions", args.completed),
        ("constraints", args.constraint),
    ):
        if values:
            current = data.get(field) if isinstance(data.get(field), list) else []
            for v in values:
                if v not in current:
                    current.append(v)
            data[field] = current[-20:]
    if args.replace_pending is not None:
        data["pending"] = list(args.replace_pending)
    save(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_clear(_: argparse.Namespace) -> int:
    data = empty()
    data["active_task"] = ""
    data["pending"] = []
    data["decisions"] = []
    data["completed_actions"] = []
    data["constraints"] = []
    save(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuity active.json CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Show active continuity")
    p_status.set_defaults(func=cmd_status)

    p_set = sub.add_parser("set", help="Update fields")
    p_set.add_argument("--task", default=None)
    p_set.add_argument("--owner", default=None)
    p_set.add_argument("--channel", default=None)
    p_set.add_argument("--pending", action="append", default=[])
    p_set.add_argument("--decision", action="append", default=[])
    p_set.add_argument("--completed", action="append", default=[])
    p_set.add_argument("--constraint", action="append", default=[])
    p_set.add_argument("--replace-pending", nargs="*", default=None)
    p_set.set_defaults(func=cmd_set)

    p_clear = sub.add_parser("clear", help="Reset active intention fields")
    p_clear.set_defaults(func=cmd_clear)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
