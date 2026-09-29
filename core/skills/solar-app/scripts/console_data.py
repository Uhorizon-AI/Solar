"""Read-only answers for the console. Nothing here creates a runtime file."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_APP = Path(__file__).resolve().parent
_STATE = _APP.parent.parent / "solar-state" / "scripts"
_PATHS = _APP.parent.parent / "solar-paths" / "scripts"
for _path in (_STATE, _PATHS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import mandates as mandate_lib  # noqa: E402
import runtime_views  # noqa: E402
import solar_runtime  # noqa: E402
import solar_state  # noqa: E402

STAMP_FRESH_SEC = 300
PASS_STAMP = ("system", "pass-stamp.json")
REQUESTER = {
    "present": True,
    "recorded": False,
    "label": "Empty until part 2. Not an authenticated identity.",
}

# What sync-clients.sh publishes. Codex and Antigravity share .agents/skills.
IDE_DESTINATIONS = (
    (".claude/skills", "symlink", ()),
    (".gemini/skills", "symlink", ()),
    (".cursor/skills", "copy", ()),
    (".agents/skills", "copy", ("codex", "antigravity")),
)
_ENV_KEYS = ("SOLAR_GATEWAY_CLAIM_TELEGRAM", "SOLAR_CLOUDFLARED_HOSTNAME")
_LABELS = {"calm": "calm", "fault": "fault", "unverified": "unverified"}
_REQUIRED_PROCESSES = ("ws", "http", "tunnel")


def _now(now=None) -> datetime:
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_seconds(value, now: datetime) -> int | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return int((now - parsed).total_seconds())


def _read_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _runtime_file(*parts: str) -> Path:
    return solar_runtime.runtime_root().joinpath(*parts)


def read_pass_stamp() -> dict | None:
    path = solar_runtime.runtime_dir("system") / "pass-stamp.json"
    data = _read_json(path)
    return data if isinstance(data, dict) else None


def read_owner() -> dict | None:
    data = _read_json(_runtime_file("workspace-owner.json"))
    if not isinstance(data, dict):
        return None
    return {
        "workspace_id": data.get("workspace_id"),
        "path": data.get("path"),
        "claimed_at": data.get("claimed_at"),
    }


def read_cutover() -> dict | None:
    data = _read_json(_runtime_file("state-cutover.json"))
    if not isinstance(data, dict):
        return None
    fmt_path = _runtime_file("STATE_FORMAT")
    fmt = None
    if fmt_path.is_file():
        fmt = fmt_path.read_text(encoding="utf-8").strip() or None
    return {"identity": data.get("identity"), "format": fmt or data.get("format")}


def read_backups() -> list[str]:
    folder = _runtime_file("state-backups", "daily")
    if not folder.is_dir():
        return []
    copies = []
    for path in sorted(folder.glob("state-*.sqlite")):
        if path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            copies.append(mtime.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return copies


def read_install(workspace: Path) -> dict:
    data = _read_json(Path(workspace) / ".solar" / "settings.json")
    if not isinstance(data, dict):
        return {"version": None, "mode": None}
    return {"version": data.get("core_version"), "mode": data.get("core_source")}


def _env_values(workspace: Path) -> dict:
    path = Path(workspace) / ".env"
    found = {}
    if not path.is_file():
        return found
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        if key in _ENV_KEYS:
            found[key] = value.strip().strip('"').strip("'")
    return found


def _stamp_values(path: Path) -> dict:
    if not path.is_file():
        return {}
    out = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _gateway_facts(probed: dict) -> dict:
    """Healthy only when local health, the connector, and every process are up."""
    processes = probed.get("processes") if isinstance(probed.get("processes"), dict) else {}
    alive = {name: bool(processes.get(name)) for name in _REQUIRED_PROCESSES}
    local_health = bool(probed.get("local_health"))
    connector = bool(probed.get("connector_ready"))
    required_up = all(alive.values())
    healthy = local_health and connector and required_up
    return {
        "state": "healthy" if healthy else "problems",
        "connector_ready": connector,
        "local_health": local_health,
        "processes_alive": required_up,
        "processes": alive,
    }


def verdict(*, stamp, db_readable: bool, port_foreign: bool, now=None) -> dict:
    """Calm, fault, or unverified. Quiet time is not a fault by itself.

    A fresh stamp is a gateway fault unless local health, the connector, and
    the ws, http, and tunnel processes are all up. No stamp leaves the pass
    and the gateway unverified.
    """
    now = _now(now)
    reasons = []
    unverified = []
    launchagent = {"state": "unverified", "at": None, "age_seconds": None}
    gateway = {"state": "unverified"}
    if not db_readable:
        reasons.append("database")
    if port_foreign:
        reasons.append("port")
    if not isinstance(stamp, dict) or not stamp.get("at"):
        unverified.extend(("launchagent", "gateway"))
    else:
        age = _age_seconds(stamp.get("at"), now)
        launchagent = {"state": "observed", "at": stamp.get("at"), "age_seconds": age}
        features = stamp.get("features") if isinstance(stamp.get("features"), dict) else {}
        if any(value == "failed" for value in features.values()):
            reasons.append("system")
        if age is None or age > STAMP_FRESH_SEC:
            reasons.append("launchagent")
            launchagent["state"] = "stale"
        else:
            probed = stamp.get("gateway")
            if not isinstance(probed, dict):
                unverified.append("gateway")
            else:
                gateway = _gateway_facts(probed)
                if gateway["state"] != "healthy":
                    reasons.append("gateway")
    if reasons:
        state = "fault"
    elif unverified:
        state = "unverified"
    else:
        state = "calm"
    return {
        "verdict": state,
        "label": _LABELS[state],
        "reasons": reasons,
        "unverified": unverified,
        "checks": _checks(
            stamp=stamp,
            db_readable=db_readable,
            port_foreign=port_foreign,
            launchagent=launchagent,
            gateway=gateway,
        ),
        "launchagent": launchagent,
        "gateway": gateway,
    }


def _checks(*, stamp, db_readable: bool, port_foreign: bool, launchagent: dict, gateway: dict) -> list[dict]:
    """Explicit state for each design check. The page renders this and does not decide it."""
    features = stamp.get("features") if isinstance(stamp, dict) and isinstance(stamp.get("features"), dict) else {}
    if any(value == "failed" for value in features.values()):
        system = "fault"
    elif launchagent.get("state") == "observed":
        system = "ok"
    else:
        system = "unverified"
    launch = launchagent.get("state")
    if launch == "stale":
        launch_state = "fault"
    elif launch == "unverified":
        launch_state = "unverified"
    else:
        launch_state = "ok"
    gateway_state = gateway.get("state")
    if gateway_state == "healthy":
        gateway_check = "ok"
    elif gateway_state == "problems":
        gateway_check = "fault"
    else:
        gateway_check = "unverified"
    return [
        {"id": "database", "state": "ok" if db_readable else "fault"},
        {"id": "port", "state": "fault" if port_foreign else "ok"},
        {"id": "system", "state": system},
        {"id": "router", "state": "fault" if not db_readable else "ok"},
        {"id": "launchagent", "state": launch_state},
        {"id": "gateway", "state": gateway_check},
    ]


def port_taken_by_other(port: int = 9000) -> bool:
    """True when something other than this console is listening on the port."""
    import subprocess
    try:
        listed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    pids = [line.strip() for line in listed.stdout.splitlines() if line.strip().isdigit()]
    if not pids:
        return False
    for pid in pids:
        try:
            shown = subprocess.run(
                ["ps", "-p", pid, "-o", "args="],
                capture_output=True, text=True, timeout=2, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        command = shown.stdout or ""
        if "host_server.py" in command:
            continue
        return True
    return False


def _with_store(fn):
    try:
        with solar_state.read_session() as store:
            return fn(store), None
    except solar_state.StateError as exc:
        return None, exc


def _activity(data, now: datetime) -> dict:
    if not isinstance(data, dict):
        return {"router": None, "tasks": None, "mandates": None}
    out = {}
    for key, value in data.items():
        out[key] = {"at": value, "age_seconds": _age_seconds(value, now)}
    return out


def health(workspace, *, port_foreign: bool = False, now=None) -> dict:
    now = _now(now)
    db_data, error = _with_store(lambda store: {
        "last_activity": runtime_views.console_last_activity(store),
        "continuity": runtime_views.console_continuity(store),
    })
    stamp = read_pass_stamp()
    decision = verdict(
        stamp=stamp,
        db_readable=error is None,
        port_foreign=port_foreign or port_taken_by_other(),
        now=now,
    )
    continuity = (db_data or {}).get("continuity") if db_data else None
    updated = continuity.get("updated_at") if isinstance(continuity, dict) else None
    install = read_install(workspace)
    return {
        "verdict": decision,
        "version": install["version"],
        "mode": install["mode"],
        "owner": read_owner(),
        "cutover": read_cutover(),
        "backups": read_backups(),
        "stamp": stamp,
        "last_activity": _activity((db_data or {}).get("last_activity"), now),
        "continuity_at": updated,
        "continuity_age_seconds": _age_seconds(updated, now),
        "database": None if error is None else {"refused": str(error)},
    }


def tasks(workspace) -> dict:
    data, error = _with_store(runtime_views.console_tasks)
    if error is not None:
        raise error
    data["requester"] = dict(REQUESTER)
    return data


def executions(workspace) -> dict:
    data, error = _with_store(runtime_views.console_executions)
    if error is not None:
        raise error
    data["requester"] = dict(REQUESTER)
    data["user_id_note"] = "Distinct user_id values. Not who requested the execution."
    return data


def continuity(workspace) -> dict:
    def read(store):
        document = runtime_views.console_continuity(store)
        return document

    document, error = _with_store(read)
    if error is not None:
        raise error
    folder = solar_runtime.runtime_dir("router", "conversations")
    summaries = []
    if folder.is_dir():
        for path in sorted(folder.glob("*-summary.txt")):
            if not path.is_file():
                continue
            try:
                with path.open(encoding="utf-8", errors="replace") as handle:
                    first = handle.readline().strip()
            except OSError:
                first = ""
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            summaries.append({
                "file": path.name,
                "date": mtime.strftime("%Y-%m-%d"),
                "first_line": first,
            })
    doc = document if isinstance(document, dict) else {}
    return {
        "at": doc.get("updated_at"),
        "active": doc.get("active", doc.get("active_task")),
        "pending": doc.get("pending"),
        "decisions": doc.get("decisions"),
        "next_owner": doc.get("next_owner"),
        "channels": doc.get("channels", doc.get("channels_seen")),
        "summaries": summaries,
        "document": document,
    }


def mandates(workspace) -> dict:
    defined = []
    modes = {}
    for path in mandate_lib.list_mandates():
        text = mandate_lib.read_text(path)
        name = mandate_lib.get_field(text, "name") or path.stem
        mode = mandate_lib.get_field(text, "mode")
        defined.append({"name": name, "file": path.name, "mode": mode})
        modes[name] = mode
    events, error = _with_store(runtime_views.console_mandate_events)
    if error is not None:
        raise error
    return {"defined": defined, "modes": modes, "events": events, "gate": _gate_decisions()}


def _gate_decisions() -> dict:
    path = solar_runtime.runtime_dir("mcp") / "audit.jsonl"
    rows = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    allowed = sum(1 for row in rows if row.get("allowed") is True)
    last = [
        {"ts": row.get("ts"), "tool": row.get("tool"), "allowed": row.get("allowed"), "code": row.get("code")}
        for row in rows[-20:]
    ]
    return {"total": len(rows), "allowed": allowed, "last": last}


def ides(workspace) -> list[dict]:
    root = Path(workspace)
    found = []
    for relative, kind, shared in IDE_DESTINATIONS:
        path = root.joinpath(*relative.split("/"))
        broken = []
        count = 0
        managed = 0
        if path.is_symlink() and not path.exists():
            broken.append(relative)
        elif path.is_dir():
            managed_file = path / ".solar-managed"
            if managed_file.is_file():
                managed = sum(1 for line in managed_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
            for child in sorted(path.iterdir()):
                if child.name == ".solar-managed":
                    continue
                if child.is_symlink() and not child.exists():
                    broken.append(child.name)
                    continue
                if child.is_dir() or child.is_symlink():
                    count += 1
        found.append({
            "destination": relative,
            "kind": kind,
            "skills": count,
            "broken": broken,
            "solar_managed": managed,
            "shared_with": list(shared),
            "present": path.exists() or path.is_symlink(),
        })
    return found


def ingress(workspace) -> dict:
    env = _env_values(workspace)
    claim = env.get("SOLAR_GATEWAY_CLAIM_TELEGRAM")
    claim_text = str(claim).strip().lower() if claim is not None else ""
    configured = claim_text in {"1", "true", "yes", "on"}
    stamp = _stamp_values(solar_runtime.runtime_dir("gateway") / "env.stamp")
    fail = _stamp_values(solar_runtime.runtime_dir("gateway") / "env.fail")
    return {
        "claim_telegram": configured,
        "claim_telegram_raw": claim if claim is not None else None,
        "claim_label": "configured to claim" if configured else "not configured to claim",
        "telegram_status": "live status not verified",
        "hostname": env.get("SOLAR_CLOUDFLARED_HOSTNAME") or None,
        "stamp": {
            "http_host": stamp.get("http_host"),
            "http_port": stamp.get("http_port"),
            "ws_port": stamp.get("ws_port"),
            "tunnel_mode": stamp.get("tunnel_mode"),
            "tunnel_name": stamp.get("tunnel_name"),
            "keys_present": stamp.get("keys_present"),
        } if stamp else None,
        "fail": {
            "reason": fail.get("reason"),
            "attempts": fail.get("attempts"),
            "exhausted": fail.get("exhausted"),
            "failed_at": fail.get("failed_at"),
            "next_retry_at": fail.get("next_retry_at"),
        } if fail else None,
    }


def requester(workspace) -> dict:
    return {
        "tasks": dict(REQUESTER),
        "executions": dict(REQUESTER),
        "approvals": dict(REQUESTER),
    }
