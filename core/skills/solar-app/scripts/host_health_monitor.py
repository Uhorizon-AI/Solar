#!/usr/bin/env python3
"""Fleet health scans → deduped inbox events (Host-2)."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import host_events
import host_registry as reg

_FAIL_WARN_RE = re.compile(r"\b(FAIL|WARN|DOWN)\b", re.IGNORECASE)
_GATEWAY_HINT_RE = re.compile(r"(gateway|transport)", re.IGNORECASE)


def _skill_script(skill: str, name: str) -> Path | None:
    root = os.environ.get("SOLAR_ROOT", "").strip()
    candidates: list[Path] = []
    if root:
        candidates.append(Path(root) / "core" / "skills" / skill / "scripts" / name)
    here = Path(__file__).resolve().parent.parent.parent / "skills" / skill / "scripts" / name
    candidates.append(here)
    for c in candidates:
        if c.is_file():
            return c
    return None


def _run_status(workspace: str, timeout: float = 30.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            reg.solar_cli_argv(workspace, "status"),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, f"status error: {exc}"


def _status_has_degraded_snippet(text: str) -> bool:
    for line in text.splitlines():
        if _FAIL_WARN_RE.search(line):
            return True
    return False


def _status_suggests_gateway_issue(text: str) -> bool:
    for line in text.splitlines():
        if _GATEWAY_HINT_RE.search(line) and _FAIL_WARN_RE.search(line):
            return True
    if "transport gateway" in text.lower() and "down" in text.lower():
        return True
    return False


def _check_gateway_script(workspace: str, timeout: float = 25.0) -> tuple[int, str]:
    script = _skill_script("solar-gateway", "check_transport_gateway.sh")
    if not script:
        return 0, ""
    env = {**os.environ, "SOLAR_WORKSPACE": workspace}
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _failed_async_jobs(workspace: str) -> list[dict]:
    return [j for j in reg.list_async_jobs(workspace) if j.get("state") == "failed"]


def scan_workspace(workspace: str, *, fleet_row: dict | None = None) -> None:
    """Emit health.degraded / gateway.error when checks fail (deduped)."""
    ws = str(Path(workspace).resolve())
    row = fleet_row or reg.workspace_health(ws)
    severity = str(row.get("severity", "OK")).upper()
    status_snip = str(row.get("status_snip") or "")
    if not status_snip:
        _, status_snip = _run_status(ws)

    reasons: list[str] = []
    if severity in ("WARN", "DOWN"):
        reasons.append(f"fleet severity={severity}")
    if _status_has_degraded_snippet(status_snip):
        reasons.append("solar status reports FAIL/WARN")

    failed_jobs = _failed_async_jobs(ws)
    if failed_jobs:
        reasons.append(f"{len(failed_jobs)} async job(s) failed")

    if reasons:
        host_events.emit_deduped(
            "health.degraded",
            {
                "summary": "; ".join(reasons)[:240],
                "severity": severity,
                "status_snip": status_snip[:400],
                "failed_async": len(failed_jobs),
                "dedupe_key": f"health:{severity}:{len(failed_jobs)}",
            },
            workspace=ws,
        )

    gateway_issue = _status_suggests_gateway_issue(status_snip)
    gw_code = 0
    gw_out = ""
    if not gateway_issue:
        gw_code, gw_out = _check_gateway_script(ws)
        gateway_issue = gw_code != 0
    elif not gw_out:
        gw_code, gw_out = _check_gateway_script(ws)

    if gateway_issue:
        summary = "transport gateway unhealthy"
        if gw_code == 2:
            summary = "transport gateway partial (tunnel/route)"
        host_events.emit_deduped(
            "gateway.error",
            {
                "summary": summary,
                "exit_code": gw_code,
                "detail": (gw_out or status_snip)[:400],
                "dedupe_key": f"gateway:{gw_code}",
            },
            workspace=ws,
        )


def scan_fleet(active_workspace: str | None = None) -> None:
    """Scan active workspace + any WARN/DOWN fleet rows."""
    fleet = reg.fleet_health(use_cache=False)
    active = active_workspace or fleet.get("active_path") or ""
    seen: set[str] = set()
    for ws in fleet.get("workspaces", []):
        path = str(ws.get("path", ""))
        if not path or path in seen:
            continue
        seen.add(path)
        sev = str(ws.get("severity", "OK")).upper()
        if path == active or sev in ("WARN", "DOWN"):
            scan_workspace(path, fleet_row=ws)
