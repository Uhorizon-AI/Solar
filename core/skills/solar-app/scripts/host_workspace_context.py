#!/usr/bin/env python3
"""Mount / unmount / switch active workspace context for Solar Host."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import host_events  # noqa: E402
import host_registry as reg  # noqa: E402

_mounted: str | None = None
_managed_env_keys: set[str] = set()
_CORE_DIR = _SCRIPT_DIR.parent.parent.parent


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def parse_workspace_env_file(ws: Path | str) -> dict[str, str]:
    ws_path = Path(ws).resolve()
    env_file = ws_path / ".env"
    out: dict[str, str] = {}
    if not env_file.is_file():
        return out
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def _clear_workspace_env() -> None:
    global _managed_env_keys  # noqa: PLW0603
    for key in _managed_env_keys:
        os.environ.pop(key, None)
    _managed_env_keys = set()


def load_workspace_env(ws: Path | str) -> None:
    """Apply workspace .env to process env, replacing keys from the previous mount."""
    global _managed_env_keys  # noqa: PLW0603
    ws_path = Path(ws).resolve()
    _clear_workspace_env()
    for key, val in parse_workspace_env_file(ws_path).items():
        os.environ[key] = val
        _managed_env_keys.add(key)
    os.environ["SOLAR_WORKSPACE"] = str(ws_path)
    _managed_env_keys.add("SOLAR_WORKSPACE")
    _apply_legacy_app_env()


def _apply_legacy_app_env() -> None:
    """Map deprecated SOLAR_HOST_* / SOLAR_INTERFACE_* keys to SOLAR_APP_*."""
    global _managed_env_keys  # noqa: PLW0603
    if not os.environ.get("SOLAR_APP_HOST"):
        for key in ("SOLAR_HOST_HOST", "SOLAR_INTERFACE_HOST"):
            val = os.environ.get(key)
            if val:
                os.environ["SOLAR_APP_HOST"] = val
                _managed_env_keys.add("SOLAR_APP_HOST")
                break
    if not os.environ.get("SOLAR_APP_PORT"):
        for key in ("SOLAR_HOST_PORT", "SOLAR_INTERFACE_PORT"):
            val = os.environ.get(key)
            if val:
                os.environ["SOLAR_APP_PORT"] = val
                _managed_env_keys.add("SOLAR_APP_PORT")
                break


def app_runtime_db_path(ws: Path | str) -> Path:
    return Path(ws) / "sun/runtime/app/db/interface.sqlite"


def app_runtime_dir(ws: Path | str) -> Path:
    return Path(ws) / "sun/runtime/app"


# Backward-compatible aliases (Host-4 transition).
def legacy_interface_db_path(ws: Path | str) -> Path:
    return app_runtime_db_path(ws)


def legacy_interface_runtime_dir(ws: Path | str) -> Path:
    return app_runtime_dir(ws)


def ensure_workspace_runtime(ws: Path | str) -> None:
    base = app_runtime_dir(ws)
    (base / "db").mkdir(parents=True, exist_ok=True)
    (base / "state").mkdir(parents=True, exist_ok=True)
    (base / "db" / "migrations").mkdir(parents=True, exist_ok=True)
    # One-release compatibility: migrate legacy runtime tree if present.
    legacy = Path(ws) / "sun/runtime/interface"
    if legacy.is_dir() and not any(base.iterdir()):
        import shutil

        for name in ("db", "state", "threads", "runs", "logs"):
            src = legacy / name
            dst = base / name
            if src.exists() and not dst.exists():
                shutil.move(str(src), str(dst))


def legacy_interface_pid_file(ws: Path | str) -> Path:
    env = parse_workspace_env_file(ws)
    runtime_rel = env.get("SOLAR_APP_RUNTIME_DIR", "sun/runtime/app").lstrip("./")
    return Path(ws).resolve() / runtime_rel / "state" / "interface.pid"


def legacy_interface_port(ws: Path | str) -> int:
    """Hash-derived port for removed :7741-era daemons (cleanup on workspace switch)."""
    return reg.legacy_daemon_port(str(Path(ws).resolve()))


def _listener_pids(port: int) -> set[int]:
    proc = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {int(line.strip()) for line in (proc.stdout or "").split() if line.strip().isdigit()}


def _pid_command(pid: int) -> str | None:
    """Return command line, '' if process gone, None if ps is unavailable (e.g. sandbox)."""
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    err = (proc.stderr or "").lower()
    if "not permitted" in err or "not permitted" in (proc.stdout or "").lower():
        return None
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _should_stop_legacy_pid(
    pid: int,
    *,
    pid_file_pid: int | None,
    listener_pids: set[int],
) -> bool:
    if pid <= 0:
        return False
    # Trusted without ps: pidfile matches the listener on this workspace's legacy port.
    if pid_file_pid is not None and pid == pid_file_pid and pid in listener_pids:
        return True
    cmd = _pid_command(pid)
    if cmd and "interface_server.py" in cmd:
        return True
    return False


def _kill_pid(pid: int) -> None:
    subprocess.run(["kill", str(pid)], check=False)
    for _ in range(20):
        if subprocess.run(["kill", "-0", str(pid)], check=False).returncode != 0:
            return
        time.sleep(0.25)
    subprocess.run(["kill", "-9", str(pid)], check=False)


def stop_legacy_interface_daemon(ws: Path | str) -> None:
    """Stop interface_server.py for a workspace (MVP-b b2: no stale listeners after switch)."""
    ws_path = Path(ws).resolve()
    pid_file = legacy_interface_pid_file(ws_path)
    port = legacy_interface_port(ws_path)
    listener_pids = _listener_pids(port)

    pid_file_pid: int | None = None
    if pid_file.is_file():
        try:
            pid_file_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid_file_pid = None

    candidates: set[int] = set(listener_pids)
    if pid_file_pid is not None and pid_file_pid > 0:
        candidates.add(pid_file_pid)

    for pid in candidates:
        if _should_stop_legacy_pid(
            pid,
            pid_file_pid=pid_file_pid,
            listener_pids=listener_pids,
        ):
            _kill_pid(pid)

    pid_file.unlink(missing_ok=True)

    for _ in range(20):
        listener_pids = _listener_pids(port)
        if not listener_pids:
            return
        for pid in listener_pids:
            if _should_stop_legacy_pid(
                pid,
                pid_file_pid=pid_file_pid,
                listener_pids=listener_pids,
            ):
                _kill_pid(pid)
        time.sleep(0.25)


def get_mounted() -> str | None:
    return _mounted


def mount(path: str) -> str:
    global _mounted  # noqa: PLW0603
    norm = _normalize_path(path)
    if not Path(norm).is_dir():
        raise ValueError(f"workspace not found: {path}")
    ensure_workspace_runtime(norm)
    load_workspace_env(norm)
    _mounted = norm
    if os.environ.get("SOLAR_ROOT", "").strip():
        import host_interface as hi  # noqa: PLC0415

        hi.invalidate_store(norm)
        hi.get_store(norm)
    return norm


def unmount() -> None:
    global _mounted  # noqa: PLW0603
    old = _mounted
    if not old:
        return
    stop_legacy_interface_daemon(old)
    reg.invalidate_fleet_cache()
    import host_interface as hi  # noqa: PLC0415

    hi.invalidate_store(old)
    _clear_workspace_env()
    _mounted = None


def switch_workspace(path: str) -> str:
    old = get_mounted()
    norm_new = _normalize_path(path)
    if old and _normalize_path(old) != norm_new:
        unmount()
    reg.set_active(path)
    mounted = mount(path)
    label = reg.workspace_label(mounted)
    host_events.emit(
        "workspace.activated",
        {"path": mounted, "label": label},
        workspace=mounted,
    )
    reg.record_metric(
        "workspace.switch",
        {"from": old or "", "to": mounted},
    )
    return mounted
