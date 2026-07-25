#!/usr/bin/env python3
"""Control A3 mandates under sun/delegations/ (fail-closed).

Universal primitive: enforces the A3 mandate contract defined in
`core/docs/authority-model.md` (limits, expiry, stop conditions, revoke,
evidence). Any caller — skill script, async task or agent — must gate mutating
work through `check` and fail closed on a non-zero exit.

"A3 mandate" here is unrelated to the router's JIT *delegation* of agents/skills.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_CLIENT = _SCRIPTS.parent.parent / "solar-client" / "scripts"
if str(_CLIENT) not in sys.path:
    sys.path.insert(0, str(_CLIENT))

from solar_paths import resolve_solar_paths  # noqa: E402

WORKSPACE, _ = resolve_solar_paths()
# Overridable so tests never touch live mandates or evidence.
DEL_DIR = Path(os.environ.get("SOLAR_DELEGATIONS_DIR") or WORKSPACE / "sun" / "delegations")
RUNTIME = Path(
    os.environ.get("SOLAR_DELEGATIONS_RUNTIME") or WORKSPACE / "sun" / "runtime" / "delegations"
)

REQUIRED_FIELDS = (
    "name",
    "owner",
    "objective",
    "allowed_actions",
    "systems",
    "limits",
    "stop_conditions",
    "valid_from",
    "expires_at",
    "revoke_with",
    "evidence_log",
)

MUTATING_ACTIONS = frozenset({"run", "send", "apply", "contact", "publish", "push"})

# Shadow is fail-closed allowlist: only these may run (and must also be in
# allowed_actions). Mandates may narrow further with a `shadow_safe_actions:` list.
DEFAULT_SHADOW_SAFE_ACTIONS = frozenset(
    {"status", "check", "dry-run", "validate", "shadow"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_mandates() -> list[Path]:
    if not DEL_DIR.exists():
        return []
    return sorted(DEL_DIR.glob("*.yaml")) + sorted(DEL_DIR.glob("*.yml"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def get_field(text: str, key: str) -> str | None:
    m = re.search(rf"^\s*{re.escape(key)}:\s*(.+)$", text, re.M)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def has_list_or_block(text: str, key: str) -> bool:
    if get_field(text, key) is not None:
        return True
    return bool(re.search(rf"(?m)^\s*{re.escape(key)}:\s*$", text))


def list_items(text: str, key: str, next_key: str) -> set[str]:
    if f"{key}:" not in text:
        return set()
    block = text.split(f"{key}:", 1)[1]
    if f"{next_key}:" in block:
        block = block.split(f"{next_key}:", 1)[0]
    return {
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*-\s*([^#\n]+?)(?:\s+#.*)?$", block)
        if match.group(1).strip()
    }


def set_field(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*).*$", re.M)
    if pattern.search(text):
        return pattern.sub(rf"\g<1>{value}", text, count=1)
    if re.search(r"^\s*mode:", text, re.M):
        return re.sub(r"(^\s*mode:\s*.*$)", rf"\1\n  {key}: {value}", text, count=1, flags=re.M)
    return text.rstrip() + f"\n  {key}: {value}\n"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().strip('"').strip("'")
    try:
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            # Date-only values are inclusive calendar days (UTC midnight).
            return datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def date_only(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def valid_shadow_evidence(
    stem: str,
    allowed_actions: set[str],
    safe_actions: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return shadow.jsonl records that count toward activate.

    Fail-closed: only JSON objects with mode=shadow, applied=false, and
    intended_action ∈ allowed_actions ∩ shadow_safe_actions.
    """
    safe = safe_actions if safe_actions is not None else set(DEFAULT_SHADOW_SAFE_ACTIONS)
    path = RUNTIME / stem / "shadow.jsonl"
    if not path.exists():
        return []
    valid: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("mode") != "shadow":
            continue
        if record.get("applied") is not False:
            continue
        action = record.get("intended_action")
        if not isinstance(action, str):
            continue
        if action not in allowed_actions or action not in safe:
            continue
        valid.append(record)
    return valid


def shadow_evidence_count(
    stem: str,
    allowed_actions: set[str] | None = None,
    safe_actions: set[str] | None = None,
) -> int:
    if allowed_actions is None:
        return 0
    return len(valid_shadow_evidence(stem, allowed_actions, safe_actions))


def runtime_events(stem: str) -> list[dict[str, Any]]:
    path = RUNTIME / stem / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def list_block_items(text: str, key: str) -> set[str]:
    """Parse a YAML list under `key:` until the next mapping key at indent ≤ 2."""
    if not re.search(rf"(?m)^\s*{re.escape(key)}\s*:", text):
        return set()
    block = re.split(rf"(?m)^\s*{re.escape(key)}\s*:", text, maxsplit=1)[1]
    items: set[str] = set()
    for line in block.splitlines():
        if re.match(r"^\s{0,2}[A-Za-z_][\w-]*\s*:", line) and not line.lstrip().startswith("-"):
            break
        match = re.match(r"^\s*-\s*([^#\n]+?)(?:\s+#.*)?$", line)
        if match and match.group(1).strip():
            items.add(match.group(1).strip().strip('"').strip("'"))
    return items


def shadow_safe_actions(text: str) -> set[str]:
    """Actions permitted while mode=shadow.

    Default allowlist is fail-closed. A mandate may only *narrow* via
    `shadow_safe_actions:` (intersection with the default) — never widen.
    """
    default = set(DEFAULT_SHADOW_SAFE_ACTIONS)
    custom = list_block_items(text, "shadow_safe_actions")
    return (custom & default) if custom else default


def parse_frequency_hours(raw: str | None) -> int | None:
    """Parse cadence. Supported: 'every|cada N hours|horas' or 'every|cada N days|días'."""
    if not raw:
        return None
    value = raw.strip().strip('"').strip("'")
    match = re.match(
        r"(?i)^(?:every|cada)\s+(\d+)\s*(?:hours?|horas?)\b",
        value,
    )
    if match:
        return int(match.group(1))
    match = re.match(
        r"(?i)^(?:every|cada)\s+(\d+)\s*(?:days?|d[ií]as?)\b",
        value,
    )
    if match:
        return int(match.group(1)) * 24
    return None


def frequency_hours(text: str) -> int | None:
    return parse_frequency_hours(get_field(text, "frequency"))


def max_items_per_day(text: str) -> int | None:
    value = get_field(text, "max_items_per_day")
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def daily_usage(events: list[dict[str, Any]], day: str | None = None) -> int:
    target = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = 0
    for event in events:
        if event.get("event") != "usage_reserved":
            continue
        if str(event.get("ts", ""))[:10] != target:
            continue
        try:
            total += max(0, int(event.get("items", 0)))
        except (TypeError, ValueError):
            continue
    return total


def runtime_limit_errors(
    path: Path,
    text: str,
    *,
    action: str | None = None,
    requested_items: int | None = None,
    operational: bool = True,
    automated: bool = False,
    events: list[dict[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []
    runtime = events if events is not None else runtime_events(path.stem)
    limit = max_items_per_day(text)
    # Volume caps apply to work that consumes quota (score/run/…), not to
    # shadow-safe probes (dry-run/validate/status).
    volume_applies = limit is not None and (
        action is None or action not in DEFAULT_SHADOW_SAFE_ACTIONS
    )
    if volume_applies:
        if requested_items is None:
            errors.append("volume limit requires --items before execution")
        elif requested_items < 1:
            errors.append("requested items must be >= 1")
        else:
            used = daily_usage(runtime)
            if used + requested_items > limit:
                errors.append(
                    f"daily volume limit: used={used} requested={requested_items} max={limit}"
                )

    if not operational:
        return errors

    if any(event.get("event") == "stop_requested" for event in runtime):
        errors.append("runtime stop requested")

    results = [event for event in runtime if event.get("event") == "execution_result"]
    consecutive_failures = 0
    for event in reversed(results):
        if event.get("result") != "failure":
            break
        consecutive_failures += 1
    if consecutive_failures >= 3:
        errors.append(f"stop condition met: consecutive failures={consecutive_failures}")

    # Cadence belongs to scheduled automation. A human asking for one more run is
    # a fresh A2, not a mandate violation. Unknown frequency strings fail closed
    # when --automated so a bad YAML cannot silently disable cadence.
    if automated:
        raw_freq = get_field(text, "frequency")
        if raw_freq:
            hours = parse_frequency_hours(raw_freq)
            if hours is None:
                errors.append(
                    f"frequency unparseable (want 'every N hours|days'): {raw_freq}"
                )
            elif results:
                last = results[-1]
                try:
                    last_ts = datetime.fromisoformat(
                        str(last.get("ts", "")).replace("Z", "+00:00")
                    )
                except ValueError:
                    last_ts = None
                if last_ts and datetime.now(timezone.utc) - last_ts < timedelta(hours=hours):
                    errors.append(f"frequency limit: last execution is less than {hours}h old")
    return errors


def validate_mandate(
    path: Path,
    *,
    for_activate: bool = False,
    for_execute: bool = False,
    action: str | None = None,
    requested_items: int | None = None,
    automated: bool = False,
) -> list[str]:
    """Return list of fail-closed errors (empty = ok)."""
    errors: list[str] = []
    text = read_text(path)
    mode = (get_field(text, "mode") or "").strip()
    name = get_field(text, "name")

    for key in REQUIRED_FIELDS:
        if key in {"allowed_actions", "systems", "limits", "stop_conditions"}:
            if not has_list_or_block(text, key):
                errors.append(f"missing required field/block: {key}")
        elif not get_field(text, key):
            errors.append(f"missing required field: {key}")

    if mode == "revoked" or get_field(text, "revoked_at"):
        errors.append("mandate is revoked")

    expires = parse_date(get_field(text, "expires_at"))
    today = date_only(datetime.now(timezone.utc))
    if expires is None:
        errors.append("expires_at unparseable or missing")
    elif date_only(expires) < today:
        errors.append(f"mandate expired at {get_field(text, 'expires_at')}")

    valid_from = parse_date(get_field(text, "valid_from"))
    if valid_from and date_only(valid_from) > today:
        errors.append(f"mandate not yet valid (valid_from={get_field(text, 'valid_from')})")

    if for_activate:
        if mode not in {"shadow", "paused"}:
            errors.append(f"activate only from shadow/paused (mode={mode})")
        allowed = list_items(text, "allowed_actions", "systems")
        if not allowed:
            allowed = list_block_items(text, "allowed_actions")
        safe = shadow_safe_actions(text)
        if shadow_evidence_count(path.stem, allowed, safe) < 1:
            errors.append(
                "no valid shadow evidence in shadow.jsonl — need JSON with "
                "mode=shadow, applied=false, intended_action in "
                "allowed_actions ∩ shadow_safe_actions"
            )

    if for_execute:
        if action and action not in {"status", "check", ""}:
            allowed = list_items(text, "allowed_actions", "systems")
            if not allowed:
                allowed = list_block_items(text, "allowed_actions")
            if action not in allowed:
                errors.append(f"action '{action}' not in allowed_actions")
            if mode == "shadow":
                safe = shadow_safe_actions(text)
                if action not in safe:
                    errors.append(
                        f"shadow mode forbids action={action} "
                        f"(not in shadow_safe_actions; safe={sorted(safe)})"
                    )
            elif mode != "active":
                errors.append(f"execute requires mode=active (mode={mode})")
            # Stop conditions and cadence apply to every executable A3 action.
            errors.extend(
                runtime_limit_errors(
                    path,
                    text,
                    action=action,
                    requested_items=requested_items,
                    operational=True,
                    automated=automated,
                )
            )
        elif mode not in {"shadow", "active", "paused", "revoked"} and mode:
            errors.append(f"execute requires mode=active (mode={mode})")

    if not name:
        errors.append("name missing")
    return errors


def find_mandate(name: str) -> Path:
    for path in list_mandates():
        text = read_text(path)
        if get_field(text, "name") == name or path.stem == name:
            return path
    raise FileNotFoundError(name)


def cmd_status(_: argparse.Namespace) -> int:
    paths = list_mandates()
    if not paths:
        print("(no mandates)")
        return 0
    for path in paths:
        text = read_text(path)
        errs = validate_mandate(path)
        health = "ok" if not errs else f"invalid({len(errs)})"
        print(
            f"- {path.name}: name={get_field(text,'name')} mode={get_field(text,'mode')} "
            f"expires={get_field(text,'expires_at')} health={health}"
        )
        for err in errs:
            print(f"    ! {err}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    path = find_mandate(args.name)
    errors = validate_mandate(
        path,
        for_execute=True,
        action=args.action,
        requested_items=args.items,
        automated=args.automated,
    )
    payload: dict[str, Any] = {
        "name": args.name,
        "path": str(path),
        "ok": not errors,
        "errors": errors,
        "mode": get_field(read_text(path), "mode"),
        "automated": bool(args.automated),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if not errors else 2


def cmd_record_usage(args: argparse.Namespace) -> int:
    """Atomically reserve daily volume before processing a batch."""
    path = find_mandate(args.name)
    text = read_text(path)
    base_errors = validate_mandate(
        path,
        for_execute=True,
        action=args.action,
        requested_items=args.items,
        automated=getattr(args, "automated", False),
    )
    if base_errors:
        print(json.dumps({"ok": False, "errors": base_errors}, ensure_ascii=False), file=sys.stderr)
        return 2

    evidence = RUNTIME / path.stem
    evidence.mkdir(parents=True, exist_ok=True)
    log = evidence / "events.jsonl"
    with log.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        locked_events: list[dict[str, Any]] = []
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                locked_events.append(event)
        volume_errors = runtime_limit_errors(
            path,
            text,
            action=args.action,
            requested_items=args.items,
            operational=False,
            events=locked_events,
        )
        if volume_errors:
            print(
                json.dumps({"ok": False, "errors": volume_errors}, ensure_ascii=False),
                file=sys.stderr,
            )
            return 2
        record = {
            "ts": utc_now(),
            "event": "usage_reserved",
            "reservation_id": str(uuid.uuid4()),
            "name": args.name,
            "action": args.action,
            "items": args.items,
        }
        fh.seek(0, 2)
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    print(json.dumps({"ok": True, **record}, ensure_ascii=False))
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    path = find_mandate(args.name)
    text = read_text(path)
    text = set_field(text, "mode", "revoked")
    text = set_field(text, "revoked_at", utc_now())
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    evidence = RUNTIME / path.stem
    evidence.mkdir(parents=True, exist_ok=True)
    log = evidence / "events.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": utc_now(), "event": "revoked", "name": args.name}) + "\n")
    print(f"revoked {path}")
    return 0


def cmd_shadow_log(args: argparse.Namespace) -> int:
    path = find_mandate(args.name)
    text = read_text(path)
    mode = get_field(text, "mode")
    if mode not in {"shadow", "active", "paused"}:
        print(f"refuse: mode={mode}", file=sys.stderr)
        return 2
    if mode == "shadow" and args.applied:
        print(
            json.dumps(
                {"ok": False, "errors": ["shadow-log refuses --applied while mode=shadow"]},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    errors = [e for e in validate_mandate(path) if "shadow evidence" not in e and "valid shadow" not in e]
    errors = [e for e in errors if not e.startswith("activate only")]
    allowed = list_items(text, "allowed_actions", "systems")
    if not allowed:
        allowed = list_block_items(text, "allowed_actions")
    if args.action not in allowed:
        errors.append(f"action '{args.action}' not in allowed_actions")
    if mode == "shadow":
        safe = shadow_safe_actions(text)
        if args.action not in safe:
            errors.append(
                f"shadow-log refuses action={args.action} "
                f"(not in shadow_safe_actions; safe={sorted(safe)})"
            )
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 2
    evidence = RUNTIME / path.stem
    evidence.mkdir(parents=True, exist_ok=True)
    log = evidence / "shadow.jsonl"
    # Evidence that unlocks activate must be mode=shadow + applied=false.
    applied = False if mode == "shadow" else bool(args.applied)
    record = {
        "ts": utc_now(),
        "event": "shadow_action",
        "name": get_field(text, "name"),
        "mode": mode,
        "intended_action": args.action,
        "details": args.details or "",
        "applied": applied,
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    """Mark active only after explicit --i-approve and fail-closed validation."""
    if not args.i_approve:
        print(
            "Refusing: pass --i-approve after the owner reviews shadow evidence (A2 formal)",
            file=sys.stderr,
        )
        return 2
    path = find_mandate(args.name)
    errors = validate_mandate(path, for_activate=True)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 2
    text = read_text(path)
    text = set_field(text, "mode", "active")
    text = set_field(text, "activated_at", utc_now())
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    evidence = RUNTIME / path.stem
    evidence.mkdir(parents=True, exist_ok=True)
    with (evidence / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": utc_now(), "event": "activated", "name": args.name}) + "\n")
    print(f"activated {path}")
    return 0


def cmd_record_result(args: argparse.Namespace) -> int:
    path = find_mandate(args.name)
    errors = validate_mandate(path)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 2
    evidence = RUNTIME / path.stem
    evidence.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": utc_now(),
        "event": "execution_result",
        "name": args.name,
        "result": args.result,
        "exit_code": args.exit_code,
    }
    with (evidence / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("check")
    p.add_argument("name")
    p.add_argument("--action", default="status")
    p.add_argument("--items", type=int, default=None)
    p.add_argument(
        "--automated",
        action="store_true",
        help="scheduled/unattended invocation: also enforce mandate cadence",
    )
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("record-usage")
    p.add_argument("name")
    p.add_argument("--action", required=True)
    p.add_argument("--items", type=int, required=True)
    p.add_argument("--automated", action="store_true")
    p.set_defaults(func=cmd_record_usage)

    p = sub.add_parser("revoke")
    p.add_argument("name")
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("shadow-log")
    p.add_argument("name")
    p.add_argument("--action", required=True)
    p.add_argument("--details", default="")
    p.add_argument("--applied", action="store_true")
    p.set_defaults(func=cmd_shadow_log)

    p = sub.add_parser("activate")
    p.add_argument("name")
    p.add_argument("--i-approve", action="store_true")
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("record-result")
    p.add_argument("name")
    p.add_argument("--result", choices=["success", "failure"], required=True)
    p.add_argument("--exit-code", type=int, required=True)
    p.set_defaults(func=cmd_record_result)

    args = parser.parse_args()
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"mandate not found: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
