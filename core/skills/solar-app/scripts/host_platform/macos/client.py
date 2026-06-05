#!/usr/bin/env python3
"""HTTP client for Solar Host — no imports from host_server (platform layer)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


def host_url() -> str:
    host = os.environ.get("SOLAR_APP_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_APP_PORT", "9000")
    return f"http://{host}:{port}"


def get_json(path: str, *, timeout: float = 4) -> Optional[Dict[str, Any]]:
    url = f"{host_url()}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def post_json(path: str, body: Optional[Dict[str, Any]] = None, *, timeout: float = 8) -> bool:
    url = f"{host_url()}{path}"
    payload = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def pending_approval_count() -> int:
    data = get_json("/api/approvals")
    if not data:
        return 0
    approvals = data.get("approvals", [])
    if not isinstance(approvals, list):
        return 0
    return sum(1 for a in approvals if isinstance(a, dict) and a.get("status") == "pending")


def list_workspaces() -> List[Dict[str, Any]]:
    data = get_json("/api/workspaces")
    if not data:
        return []
    workspaces = data.get("workspaces", [])
    return [w for w in workspaces if isinstance(w, dict)]


def switch_workspace(path: str) -> bool:
    return post_json("/api/workspaces/active", {"path": path})


def fetch_events(*, limit: int = 30, types: str) -> List[Dict[str, Any]]:
    data = get_json(f"/api/events?limit={limit}&types={types}")
    if not data:
        return []
    events = data.get("events", [])
    return [e for e in events if isinstance(e, dict)]
