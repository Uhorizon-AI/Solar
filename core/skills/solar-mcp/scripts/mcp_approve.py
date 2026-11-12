"""The approval store behind the MCP gate: grant and list.

The server calls grant only following the user's accepted form response. There is no console
CLI: when a client does not raise the form, the human operator uses `solar approve`
(operator_approve.py), which runs the operation itself and leaves no grant behind. See
references/approvals.md for the trust boundary.

An approval names one tool and one exact set of arguments, expires (15 minutes
by default) and is burned the first time it is used.
"""
from __future__ import annotations

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
