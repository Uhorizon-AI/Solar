#!/usr/bin/env python3
"""Global multi-workspace registry for Solar Host (machine-local)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from host_platform.paths import host_global_dir  # noqa: E402

REGISTRY_DIR = host_global_dir()
REGISTRY_FILE = REGISTRY_DIR / "workspaces.json"
METRICS_FILE = REGISTRY_DIR / "host-metrics.jsonl"

_FLEET_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_FLEET_CACHE_TTL = 30.0


def invalidate_fleet_cache() -> None:
    global _FLEET_CACHE  # noqa: PLW0603
    _FLEET_CACHE = {"ts": 0.0, "payload": None}

_GOVERNANCE_PREFIXES = ("sun/", "planets/")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(workspace: str) -> int:
    proc = subprocess.run(
        ["cksum"],
        input=workspace.encode(),
        capture_output=True,
        check=True,
    )
    return int(proc.stdout.split()[0])


def port_offsets(workspace: str) -> tuple[int, int]:
    h = stable_hash(workspace)
    return 7741 + h % 500, 8787 + h % 500


def _default_registry(seed: str | None = None) -> dict[str, Any]:
    active = seed or os.environ.get("SOLAR_WORKSPACE", "")
    active = str(Path(active).resolve()) if active else ""
    workspaces: list[dict[str, Any]] = []
    if active and Path(active).is_dir():
        workspaces.append({"path": active, "label": Path(active).name, "added_at": _now_iso()})
    return {"version": 1, "active_path": active, "workspaces": workspaces}


def load_registry() -> dict[str, Any]:
    if not REGISTRY_FILE.exists():
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        data = _default_registry()
        save_registry(data)
        return data
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = _default_registry()
        save_registry(data)
        return data
    if not isinstance(data, dict):
        data = _default_registry()
        save_registry(data)
    data.setdefault("version", 1)
    data.setdefault("workspaces", [])
    data.setdefault("active_path", "")
    return data


def save_registry(data: dict[str, Any]) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def list_workspaces(data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    reg = data or load_registry()
    active = str(reg.get("active_path", "")).strip()
    out: list[dict[str, Any]] = []
    for item in reg.get("workspaces", []):
        if not isinstance(item, dict):
            continue
        path = item.get("path", "")
        if not path:
            continue
        p = Path(path)
        iface_base = "in-process" if path == active else "offline"
        out.append(
            {
                "path": path,
                "label": item.get("label") or p.name,
                "added_at": item.get("added_at", ""),
                "exists": p.is_dir(),
                "active": path == active,
                "interface_base": iface_base,
            }
        )
    return out


def workspace_label(path: str, data: dict[str, Any] | None = None) -> str:
    norm = _normalize_path(path)
    for ws in list_workspaces(data):
        if ws.get("path") == norm:
            return str(ws.get("label") or Path(norm).name)
    return Path(norm).name


def get_active_path(data: dict[str, Any] | None = None) -> str:
    reg = data or load_registry()
    active = str(reg.get("active_path", "")).strip()
    if active and Path(active).is_dir():
        return _normalize_path(active)
    workspaces = list_workspaces(reg)
    for ws in workspaces:
        if ws.get("exists"):
            set_active(ws["path"], reg)
            return ws["path"]
    seed = os.environ.get("SOLAR_WORKSPACE", "")
    if seed and Path(seed).is_dir():
        add_workspace(seed, reg=reg)
        set_active(seed, reg)
        return _normalize_path(seed)
    return ""


def set_active(path: str, reg: dict[str, Any] | None = None) -> dict[str, Any]:
    data = reg or load_registry()
    norm = _normalize_path(path)
    if not Path(norm).is_dir():
        raise ValueError(f"workspace not found: {path}")
    found = False
    for item in data.get("workspaces", []):
        if isinstance(item, dict) and item.get("path") == norm:
            found = True
            break
    if not found:
        add_workspace(norm, reg=data)
    data["active_path"] = norm
    save_registry(data)
    return data


def add_workspace(path: str, label: str | None = None, reg: dict[str, Any] | None = None) -> dict[str, Any]:
    data = reg or load_registry()
    norm = _normalize_path(path)
    if not Path(norm).is_dir():
        raise ValueError(f"workspace not found: {path}")
    workspaces = data.setdefault("workspaces", [])
    for item in workspaces:
        if isinstance(item, dict) and item.get("path") == norm:
            if label:
                item["label"] = label
            save_registry(data)
            return data
    workspaces.append(
        {"path": norm, "label": label or Path(norm).name, "added_at": _now_iso()}
    )
    if not data.get("active_path"):
        data["active_path"] = norm
    save_registry(data)
    return data


def remove_workspace(path: str, reg: dict[str, Any] | None = None) -> dict[str, Any]:
    data = reg or load_registry()
    norm = _normalize_path(path)
    data["workspaces"] = [
        w for w in data.get("workspaces", [])
        if not (isinstance(w, dict) and w.get("path") == norm)
    ]
    if data.get("active_path") == norm:
        remaining = [w for w in data["workspaces"] if isinstance(w, dict) and w.get("path")]
        data["active_path"] = remaining[0]["path"] if remaining else ""
    save_registry(data)
    return data


def _interface_port_from_env(workspace: str) -> int | None:
    env_file = Path(workspace) / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("SOLAR_INTERFACE_PORT="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def solar_cli_for(workspace: str) -> str:
    ws = Path(workspace)
    candidates = [
        ws / "core/skills/solar-interface/scripts/solar",
        Path(os.environ.get("SOLAR_ROOT", "")) / "core/skills/solar-interface/scripts/solar",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return "solar"


def _fetch_json(url: str, method: str = "GET", timeout: float = 5.0) -> tuple[int, Any]:
    req = urllib.request.Request(url, method=method, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.reason}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def workspace_health(workspace: str, timeout: float = 8.0) -> dict[str, Any]:
    ws = _normalize_path(workspace)
    if not Path(ws).is_dir():
        return {"path": ws, "severity": "DOWN", "detail": "path missing"}

    active = get_active_path()
    if ws == active:
        iface_base = "in-process"
        try:
            import host_interface as hi  # noqa: PLC0415

            store = hi.get_store(ws)
            ready, _ = store.readiness()
            iface_ok = ready
        except Exception:  # noqa: BLE001
            iface_ok = False
    else:
        iface_base = "offline"
        try:
            import host_workspace_context as ctx  # noqa: PLC0415

            iface_ok = ctx.legacy_interface_db_path(ws).is_file()
        except Exception:  # noqa: BLE001
            iface_ok = False

    solar_bin = solar_cli_for(ws)
    status_snip = ""
    severity = "OK"
    try:
        proc = subprocess.run(
            ["bash", solar_bin, "status"],
            cwd=ws,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        status_snip = (proc.stdout or proc.stderr or "")[:800]
        if proc.returncode != 0:
            severity = "WARN"
    except Exception as exc:  # noqa: BLE001
        status_snip = f"status error: {exc}"
        severity = "WARN"
    if not iface_ok and severity == "OK":
        severity = "WARN"
    return {
        "path": ws,
        "label": Path(ws).name,
        "interface_base": iface_base,
        "interface_ok": iface_ok,
        "workspace_api_ok": iface_ok,
        "severity": severity,
        "status_snip": status_snip,
    }


def fleet_health(use_cache: bool = True) -> dict[str, Any]:
    global _FLEET_CACHE  # noqa: PLW0603
    now = time.time()
    if use_cache and _FLEET_CACHE.get("payload") and now - float(_FLEET_CACHE["ts"]) < _FLEET_CACHE_TTL:
        return _FLEET_CACHE["payload"]
    reg = load_registry()
    active = get_active_path(reg)
    items = []
    for ws in list_workspaces(reg):
        if not ws.get("exists"):
            items.append({**ws, "severity": "DOWN", "detail": "path missing"})
            continue
        h = workspace_health(ws["path"])
        items.append({**ws, **h})
    payload = {"active_path": active, "workspaces": items, "cached_at": _now_iso()}
    _FLEET_CACHE = {"ts": now, "payload": payload}
    return payload


def list_async_jobs(workspace: str) -> list[dict[str, Any]]:
    root = Path(workspace) / "sun/runtime/async-tasks"
    jobs: list[dict[str, Any]] = []
    for sub, state in (("queued", "queued"), ("running", "running"), ("failed", "failed")):
        d = root / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"file": f.name}
            jobs.append(
                {
                    "id": f.stem,
                    "state": state,
                    "file": str(f.relative_to(root)),
                    "summary": data.get("summary") or data.get("title") or f.stem,
                    "mtime": f.stat().st_mtime,
                }
            )
    jobs.sort(key=lambda j: j.get("mtime", 0), reverse=True)
    return jobs[:50]


def governance_resolve(workspace: str, rel_path: str) -> Path | None:
    rel = rel_path.strip().lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    if not any(rel.startswith(p) for p in _GOVERNANCE_PREFIXES):
        return None
    base = Path(workspace).resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def record_metric(event: str, detail: dict[str, Any] | None = None) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": _now_iso(), "event": event, "detail": detail or {}}
    with METRICS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _host_base_url() -> str:
    host = os.environ.get("SOLAR_HOST_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_HOST_PORT", "9000")
    return f"http://{host}:{port}"


def switch_via_host_api(path: str, timeout: float = 10.0) -> bool:
    """Switch active workspace on the running Host daemon (no-op if Host is down)."""
    norm = _normalize_path(path)
    if "/tmp/" in norm or "/T/tmp." in norm or "/var/folders/" in norm:
        return False
    base = _host_base_url()
    code, _ = _fetch_json(f"{base}/health", timeout=min(timeout, 3.0))
    if code != 200:
        return False
    body = json.dumps({"path": norm}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/workspaces/active",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def switch_active_workspace(path: str) -> str:
    """Prefer live Host API when reachable; otherwise switch in this process."""
    offline = os.environ.get("SOLAR_HOST_OFFLINE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not offline and switch_via_host_api(path):
        active = get_active_path()
        if active:
            return active
    import host_workspace_context as ctx  # noqa: PLC0415

    return ctx.switch_workspace(path)


def _cli() -> int:
    import sys

    if len(sys.argv) < 2:
        print("Usage: host_registry.py {list|add|remove|use|active|json-fleet}", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "list":
        print(json.dumps(list_workspaces(), indent=2))
        return 0
    if cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: host_registry.py add <path> [label]", file=sys.stderr)
            return 2
        label = sys.argv[3] if len(sys.argv) > 3 else None
        add_workspace(sys.argv[2], label)
        print(f"OK: added {sys.argv[2]}")
        return 0
    if cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: host_registry.py remove <path>", file=sys.stderr)
            return 2
        remove_workspace(sys.argv[2])
        print(f"OK: removed {sys.argv[2]}")
        return 0
    if cmd == "use":
        if len(sys.argv) < 3:
            print("Usage: host_registry.py use <path>", file=sys.stderr)
            return 2
        try:
            switch_active_workspace(sys.argv[2])
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"OK: active {get_active_path()}")
        return 0
    if cmd == "active":
        print(get_active_path())
        return 0
    if cmd == "json-fleet":
        print(json.dumps(fleet_health(use_cache=False), indent=2))
        return 0
    if cmd == "ports":
        if len(sys.argv) < 3:
            print("Usage: host_registry.py ports <workspace>", file=sys.stderr)
            return 2
        ws = _normalize_path(sys.argv[2])
        iface = _interface_port_from_env(ws) or port_offsets(ws)[0]
        gw = port_offsets(ws)[1]
        print(iface, gw)
        return 0
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
