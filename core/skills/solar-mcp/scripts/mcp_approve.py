"""Grant, list and revoke the approvals the MCP gate asks for.

The normal workflow is native client confirmation: the server calls grant only
following the user's accepted form response. This CLI remains a trusted operator
recovery path, not an agent self-approval route. It does not attest to an earlier
conversation. See references/approvals.md for the trust boundary.

    python3 mcp_approve.py grant solar_task_create --args '{"title":"Revisar X"}'
    python3 mcp_approve.py list
    python3 mcp_approve.py revoke <approval_id>

An approval names one tool and one exact set of arguments, expires (15 minutes
by default) and is burned the first time it is used.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_gate


def grant(tool: str, arguments: dict, ttl: int, note: str) -> dict:
    approval_id = uuid.uuid4().hex[:16]
    record = dict(
        approval_id=approval_id, tool=tool, arguments=arguments,
        scope_hash=mcp_gate.scope_hash(tool, arguments),
        granted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        expires_at=time.time() + ttl, ttl_seconds=ttl, note=note, consumed_at=None,
    )
    folder = mcp_gate.approvals_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(folder / f"{approval_id}.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
    return record


def listing() -> list:
    folder = mcp_gate.approvals_dir()
    rows = []
    if not folder.is_dir():
        return rows
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append(dict(approval_id=record.get("approval_id"), tool=record.get("tool"),
                         granted_at=record.get("granted_at"),
                         consumed_at=record.get("consumed_at"),
                         expired=float(record.get("expires_at") or 0) < time.time()))
    return rows


def revoke(approval_id: str) -> bool:
    if not approval_id or not all(c in "0123456789abcdef" for c in approval_id):
        return False
    path = mcp_gate.approvals_dir() / f"{approval_id}.json"
    try:
        path.unlink()
        return True
    except OSError:
        return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    granter = sub.add_parser("grant")
    granter.add_argument("tool")
    granter.add_argument("--args", default="{}", help="JSON object, exactly as the caller will send it")
    granter.add_argument("--ttl", type=int, default=900)
    granter.add_argument("--note", default="")
    sub.add_parser("list")
    revoker = sub.add_parser("revoke")
    revoker.add_argument("approval_id")

    options = parser.parse_args(argv[1:])
    if options.command == "grant":
        try:
            arguments = json.loads(options.args)
            if not isinstance(arguments, dict):
                raise ValueError("--args must be a JSON object")
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        record = grant(options.tool, arguments, options.ttl, options.note)
        print(json.dumps(record, indent=2, sort_keys=True))
    elif options.command == "list":
        print(json.dumps(listing(), indent=2, sort_keys=True))
    else:
        print(json.dumps(dict(revoked=revoke(options.approval_id))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
