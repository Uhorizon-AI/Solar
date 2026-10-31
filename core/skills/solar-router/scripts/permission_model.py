"""Vocabulary shared by the permission checks and the providers.

Constants and the `Finding` record only, with no import from the router: `providers/base.py`
and `cli_permissions.py` both depend on this module, so neither needs the other at import time.
`cli_permissions` re-exports every name here.
"""
from __future__ import annotations

from dataclasses import dataclass

OK, MISSING, TOO_PERMISSIVE, UNKNOWN = "ok", "missing", "too_permissive", "unknown"
STATUSES = (OK, MISSING, TOO_PERMISSIVE, UNKNOWN)
CHECKS = ("mcp_read", "write_guard", "restricted_reader")
CLIENTS = ("claude", "codex", "agent", "agy")
MCP_SERVER = "solar"
MCP_READ_TOOLS = ("solar_search", "solar_docs")


@dataclass(frozen=True)
class Finding:
    cli: str
    check: str
    status: str
    tier: str = "static"  # static | probe
    detail: str = ""
    setting: str = ""  # the exact setting to change, empty when nothing is to change
    file: str = ""
    fix: str = ""
    snippet: str = ""  # literal text to paste, when the CLI's docs or a live run confirm its syntax

    def __post_init__(self):
        if self.status not in STATUSES or self.check not in CHECKS:
            raise ValueError(f"invalid finding {self.check}={self.status}")


def unknown(cli, check, detail, *, tier="static", fix=""):
    """What is not verified is never `ok`."""
    return Finding(cli, check, UNKNOWN, tier, detail, fix=fix)
