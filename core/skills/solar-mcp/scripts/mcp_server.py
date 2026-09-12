"""Solar MCP server: context as resources, verbs as tools behind a gate.

    resources  read-only projections of what Solar already knows. Open.
    tools      verbs. Every call goes through `mcp_gate.preflight` first, and a
               refusal is produced by this handler, not by the caller's manners.

The verbs wrap what already exists —`solar-async-tasks`' `create.sh`, the task
files, the registered action skills— instead of reimplementing any of it.

Speaks JSON-RPC 2.0 over stdio (MCP): `initialize`, `resources/list`,
`resources/read`, `tools/list`, `tools/call`, `ping`.

    python3 mcp_server.py            # serve on stdio

The installation credentials Solar sends with no longer live in the workspace:
`solar_secrets` holds them in a 0600 file outside every tree an IDE indexes, and
`solar_telegram_send` is the route an agent has to Telegram. That closes the
mediated path, not the machine — a process running as the user can still read
that file, and a browser session already logged in is not covered at all.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]
for _extra in ("solar-app/scripts", "solar-client/scripts"):
    _path = _SKILLS / _extra
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app_solar  # noqa: E402
import mcp_gate  # noqa: E402
from mcp_gate import A0, A2, A3  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = dict(name="solar-mcp", version="0.1.0")
ASYNC_SCRIPTS = _SKILLS / "solar-async-tasks" / "scripts"


def workspace() -> Path:
    return Path(os.environ.get("SOLAR_WORKSPACE") or Path.cwd())


def action_skills() -> dict:
    """Which action skills are reachable as verbs. Empty until Louis fills it.

    Instruction skills never appear here: they stay native to the harness.
    """
    path = mcp_gate.gate_root() / "action-skills.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


TOOLS = {
    "solar_task_status": dict(
        authority=A0,
        description="Read the state of the async task queue. Read-only.",
        inputSchema=dict(type="object", properties=dict(
            task_id=dict(type="string", description="Optional: one task by id or file stem."),
            state=dict(type="string", description="Optional: drafts|queued|active|error|completed."),
        ), additionalProperties=False),
    ),
    "solar_task_create": dict(
        authority=A2,
        description=("Create an async task file. Mutates the queue, so it needs an "
                     "approval id granted out of band with mcp_approve.py."),
        inputSchema=dict(type="object", properties=dict(
            title=dict(type="string"),
            description=dict(type="string"),
            queued=dict(type="boolean", description="Queue it directly instead of drafts/."),
            approval_id=dict(type="string", description="Approval granted by Louis for this exact call."),
        ), required=["title"], additionalProperties=False),
    ),
    "solar_telegram_send": dict(
        authority=A2,
        external_communication=True,
        description=("Send one Telegram message as the Solar runtime. This is the only "
                     "route an agent has to Telegram: the bot token is an installation "
                     "secret the server holds, not a key in the workspace. Sending outside "
                     "the machine is never implicit, so it needs an approval granted out "
                     "of band with mcp_approve.py, bound to this exact text."),
        inputSchema=dict(type="object", properties=dict(
            text=dict(type="string", description="The message, exactly as it will be sent."),
            chat_id=dict(type="string", description="Optional: an allowlisted chat. Defaults to TELEGRAM_CHAT_ID."),
            parse_mode=dict(type="string", description="Optional: Markdown (default) or HTML."),
            approval_id=dict(type="string", description="Approval granted by Louis for this exact send."),
        ), required=["text"], additionalProperties=False),
    ),
    "solar_action_run": dict(
        authority=A3,
        description=("Run one registered action of one registered action skill, under a "
                     "live A3 mandate. Instruction skills are not reachable here."),
        inputSchema=dict(type="object", properties=dict(
            skill=dict(type="string"),
            action=dict(type="string"),
            mandate=dict(type="string", description="Mandate to execute under."),
            automated=dict(type="boolean", description="Unattended run: cadence is enforced too."),
        ), required=["skill", "action"], additionalProperties=False),
    ),
}

RESOURCES = [
    dict(uri="solar://health", name="Solar health",
         description="Storage, gateway and continuity as the console sees them.",
         mimeType="application/json"),
    dict(uri="solar://tasks", name="Async task queue",
         description="Every task file, by state, with its recurrence.",
         mimeType="application/json"),
    dict(uri="solar://index", name="SQLite projection",
         description="Counters of the derived index and which sources went stale.",
         mimeType="application/json"),
    dict(uri="solar://delegations", name="A3 mandates",
         description="Written mandates: mode, validity and allowed actions.",
         mimeType="application/json"),
    dict(uri="solar://gate", name="Gate decisions",
         description="What this server allowed and refused, most recent last.",
         mimeType="application/json"),
]


# --------------------------------------------------------------------------
# resources
# --------------------------------------------------------------------------

def _read_health() -> dict:
    snapshot = app_solar.snapshot(workspace())
    return dict(status=snapshot["health"]["status"], counts=snapshot["counts"],
                components=[dict(component=row["component"], state=row["state"])
                            for row in snapshot["health"]["components"]])


def _read_tasks() -> dict:
    tasks, problems = app_solar.read_tasks(workspace())
    return dict(count=len(tasks), problems=len(problems), tasks=[
        dict(id=row["id"], title=row["title"], state=row["state"],
             recurring=row["recurring"], recurring_run_count=row["recurring_run_count"],
             recurring_last_run=row["recurring_last_run"], file=row["file"])
        for row in tasks])


def _read_index() -> dict:
    try:
        import app_index
    except ImportError as exc:  # pragma: no cover
        return dict(available=False, reason=str(exc))
    path = app_index.index_path()
    if not path.exists():
        return dict(available=False, reason="index not built", path=str(path))
    stale = app_index.stale_sources()
    return dict(available=True, path=str(path), counters=app_index.counters(),
                stale=stale, fresh=not stale)


def _read_delegations() -> dict:
    root = Path(os.environ.get("SOLAR_DELEGATIONS_DIR") or (workspace() / "sun" / "delegations"))
    mandates = []
    try:
        paths = sorted(p for p in root.iterdir() if p.suffix in (".yaml", ".yml"))
    except OSError:
        return dict(root=str(root), mandates=[], readable=False)
    for path in paths:
        fields = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.strip().partition(":")
            if sep and key in ("name", "mode", "valid_from", "expires_at"):
                fields.setdefault(key, value.strip().strip('"').strip("'"))
        mandates.append(dict(file=path.name, **fields))
    return dict(root=str(root), readable=True, mandates=mandates)


def _read_gate(limit: int = 20) -> dict:
    path = mcp_gate.gate_root() / "audit.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return dict(decisions=[], path=str(path))
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return dict(path=str(path), decisions=rows)


READERS = {
    "solar://health": _read_health,
    "solar://tasks": _read_tasks,
    "solar://index": _read_index,
    "solar://delegations": _read_delegations,
    "solar://gate": _read_gate,
}


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

def _do_task_status(arguments: dict) -> dict:
    data = _read_tasks()
    task_id = arguments.get("task_id")
    state = arguments.get("state")
    rows = data["tasks"]
    if state:
        rows = [row for row in rows if row["state"] == state]
    if task_id:
        rows = [row for row in rows if row["id"] == task_id
                or Path(row["file"]).stem == task_id]
    return dict(count=len(rows), tasks=rows)


def _do_task_create(arguments: dict) -> dict:
    cmd = ["bash", str(ASYNC_SCRIPTS / "create.sh")]
    if arguments.get("queued"):
        cmd.append("--queued")
    cmd.append(str(arguments["title"]))
    if arguments.get("description"):
        cmd.append(str(arguments["description"]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                          cwd=str(workspace()))
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "create.sh failed").strip()[:500])
    return dict(created=True, output=(proc.stdout or "").strip()[:1000])


def _telegram_chat_allowed(chat_id: str, env: dict) -> bool:
    """Same allowlist rule the task notifier uses: a named chat, or the default."""
    allowed = (env.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").strip()
    if allowed:
        return chat_id in {part.strip() for part in allowed.split(",") if part.strip()}
    return bool(chat_id) and chat_id == (env.get("TELEGRAM_CHAT_ID") or "").strip()


def _do_telegram_send(arguments: dict) -> dict:
    """Send as the Solar runtime. Reached only with an approval: see the gate.

    The token never touches the workspace. It is read here, from the installation
    secret store, and handed to `send_telegram.sh` through the environment — that
    script refuses to look it up on its own, so this is the mediated route.
    """
    import solar_secrets

    env = dict(os.environ)
    # Visible configuration still lives in the workspace, and the sender only
    # ever reads the TELEGRAM_* half of it; nothing else from `.env` is carried
    # into the subprocess.
    env.update({key: value
                for key, value in solar_secrets.parse_env_file(workspace() / ".env").items()
                if key.startswith("TELEGRAM_")})
    # The secret comes from the store, through the loader that allows only the
    # installation's own names. A stray key in that file reaches nothing.
    solar_secrets.load_into_environ(env)

    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "No TELEGRAM_BOT_TOKEN in the installation secret store "
            f"({solar_secrets.secrets_file()}). The server sends with the process "
            "credentials or it does not send.")

    chat_id = str(arguments.get("chat_id") or env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not _telegram_chat_allowed(chat_id, env):
        raise RuntimeError(f"chat_id {chat_id or '(none)'} is not an allowlisted chat")

    env["TELEGRAM_BOT_TOKEN"] = token
    env["TELEGRAM_CHAT_ID"] = chat_id
    if arguments.get("parse_mode"):
        env["TELEGRAM_PARSE_MODE"] = str(arguments["parse_mode"])

    script = _SKILLS / "solar-telegram" / "scripts" / "send_telegram.sh"
    proc = subprocess.run(["bash", str(script), str(arguments["text"])],
                          capture_output=True, text=True, timeout=60,
                          cwd=str(workspace()), env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "send failed").strip()[:500])
    return dict(sent=True, chat_id=chat_id, output=(proc.stdout or "").strip()[:500])


def _do_action_run(arguments: dict) -> dict:
    entry = action_skills().get(arguments["skill"], {})
    command = list(entry.get("command") or [])
    if not command:
        raise RuntimeError(f"{arguments['skill']} has no command registered")
    proc = subprocess.run(command + [str(arguments["action"])],
                          capture_output=True, text=True, timeout=600,
                          cwd=str(workspace()))
    return dict(exit_code=proc.returncode,
                stdout=(proc.stdout or "").strip()[:2000],
                stderr=(proc.stderr or "").strip()[:1000])


HANDLERS = {
    "solar_task_status": _do_task_status,
    "solar_task_create": _do_task_create,
    "solar_telegram_send": _do_telegram_send,
    "solar_action_run": _do_action_run,
}


def call_tool(name: str, arguments: dict) -> tuple[dict, bool]:
    """Gate first, then act. There is no path to a handler that skips this."""
    registry = dict(TOOLS)
    registry["_action_skills"] = action_skills()
    verdict = mcp_gate.preflight(name, arguments, registry)
    mcp_gate.record(verdict, arguments)
    if not verdict.allowed:
        return dict(refused=verdict.as_dict()), True
    try:
        result = HANDLERS[name](arguments or {})
    except Exception as exc:  # the verb failed; the approval is not burned
        return dict(error=str(exc)[:500], verdict=verdict.as_dict()), True
    mcp_gate.consume(name, arguments, registry)
    return dict(result=result, verdict=verdict.as_dict()), False


# --------------------------------------------------------------------------
# JSON-RPC over stdio
# --------------------------------------------------------------------------

def _text(payload) -> list:
    return [dict(type="text", text=json.dumps(payload, indent=2, sort_keys=True, default=str))]


def handle(message: dict) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        result = dict(protocolVersion=PROTOCOL_VERSION, serverInfo=SERVER_INFO,
                      capabilities=dict(resources=dict(listChanged=False), tools=dict(listChanged=False)),
                      instructions=("Resources are open context. Tools are gated verbs: the "
                                    "handler validates authority and mandate and refuses on its "
                                    "own. Approvals are granted out of band, never by the caller."))
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return None
    elif method == "ping":
        result = {}
    elif method == "resources/list":
        result = dict(resources=RESOURCES)
    elif method == "resources/read":
        uri = params.get("uri", "")
        reader = READERS.get(uri)
        if reader is None:
            return _error(request_id, -32602, f"Unknown resource: {uri}")
        result = dict(contents=[dict(uri=uri, mimeType="application/json",
                                     text=json.dumps(reader(), indent=2, sort_keys=True, default=str))])
    elif method == "tools/list":
        result = dict(tools=[dict(name=name, description=spec["description"],
                                  inputSchema=spec["inputSchema"])
                             for name, spec in TOOLS.items()])
    elif method == "tools/call":
        payload, is_error = call_tool(params.get("name", ""), params.get("arguments") or {})
        result = dict(content=_text(payload), isError=is_error)
    elif method == "shutdown":
        result = {}
    else:
        return _error(request_id, -32601, f"Unknown method: {method}")

    if request_id is None:
        return None
    return dict(jsonrpc="2.0", id=request_id, result=result)


def _error(request_id, code: int, message: str) -> dict:
    return dict(jsonrpc="2.0", id=request_id, error=dict(code=code, message=message))


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            stdout.write(json.dumps(_error(None, -32700, "Parse error")) + "\n")
            stdout.flush()
            continue
        try:
            response = handle(message)
        except Exception as exc:  # never take the server down for one bad call
            response = _error(message.get("id"), -32603, str(exc)[:300])
        if response is not None:
            stdout.write(json.dumps(response, default=str) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
