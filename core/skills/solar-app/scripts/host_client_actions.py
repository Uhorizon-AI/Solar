#!/usr/bin/env python3
"""Allowlisted solar CLI actions for Host dashboard (Host-2)."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import host_events
import host_registry as reg

ALLOWED = frozenset({"sync", "client_doctor", "workspace_doctor"})
_OUTPUT_CAP = 32 * 1024
_SYNC_TIMEOUT = 120
_DOCTOR_TIMEOUT = 60

_lock = threading.Lock()
_busy = False


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[: _OUTPUT_CAP - 24] + "\n…(output truncated)"


def is_loopback_client(handler: Any) -> bool:
    addr = str(getattr(handler, "client_address", ("", 0))[0] or "")
    return addr in ("127.0.0.1", "::1", "localhost", "")


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _local_hostname(hostname: str) -> bool:
    return (hostname or "").lower().strip("[]") in _LOCAL_HOSTS


def validate_origin(handler: Any, host_port: int) -> bool:
    """Reject cross-origin POSTs that could drive local CLI from another site."""
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if not _local_hostname(parsed.hostname or ""):
        return False
    if parsed.port not in (None, host_port):
        return False
    return True


def validate_host_header(handler: Any, host_port: int) -> bool:
    """Reject Host headers that do not target this local listener (DNS rebinding)."""
    raw = (handler.headers.get("Host") or "").strip()
    if not raw:
        return True
    if "@" in raw or "/" in raw or " " in raw:
        return False
    if raw.startswith("["):
        end = raw.find("]")
        if end == -1:
            return False
        hostname = raw[1:end]
        port_part = raw[end + 1 :]
    else:
        if raw.count(":") > 1:
            return False
        host_port_split = raw.rsplit(":", 1)
        if len(host_port_split) == 2 and host_port_split[1].isdigit():
            hostname, port_part = host_port_split[0], f":{host_port_split[1]}"
        else:
            hostname, port_part = raw, ""
    if not _local_hostname(hostname):
        return False
    if port_part:
        try:
            port = int(port_part.lstrip(":"))
        except ValueError:
            return False
        if port != host_port:
            return False
    return True


def validate_client_request(handler: Any, host_port: int) -> bool:
    return validate_origin(handler, host_port) and validate_host_header(handler, host_port)


def _cli_args(action: str, strict: bool) -> list[str]:
    if action == "sync":
        return ["client", "sync"]
    if action == "client_doctor":
        args = ["client", "doctor"]
        if strict:
            args.append("--strict")
        return args
    if action == "workspace_doctor":
        return ["workspace", "doctor"]
    raise ValueError(f"unknown action: {action}")


def run_action(workspace: str, action: str, *, strict: bool = False) -> tuple[int, dict[str, Any]]:
    global _busy  # noqa: PLW0603
    if action not in ALLOWED:
        return 400, {"ok": False, "error": "action not allowed", "allowed": sorted(ALLOWED)}
    if not _lock.acquire(blocking=False):
        return 409, {"ok": False, "error": "another client action is in progress"}
    _busy = True
    try:
        ws = str(Path(workspace).resolve())
        timeout = _SYNC_TIMEOUT if action == "sync" else _DOCTOR_TIMEOUT
        proc = subprocess.run(
            reg.solar_cli_argv(ws, *_cli_args(action, strict)),
            cwd=ws,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "SOLAR_WORKSPACE": ws},
        )
        output = _truncate((proc.stdout or "") + (proc.stderr or ""))
        payload: dict[str, Any] = {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": output,
            "action": action,
        }
        if proc.returncode != 0:
            host_events.emit(
                "client.action.failed",
                {
                    "summary": f"{action} failed (exit {proc.returncode})",
                    "action": action,
                    "exit_code": proc.returncode,
                },
                workspace=ws,
            )
        return 200, payload
    except subprocess.TimeoutExpired:
        host_events.emit(
            "client.action.failed",
            {"summary": f"{action} timed out", "action": action, "exit_code": -1},
            workspace=workspace,
        )
        return 200, {"ok": False, "exit_code": -1, "output": "timeout", "action": action}
    finally:
        _busy = False
        _lock.release()
