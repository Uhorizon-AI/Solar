"""Solar MCP server: three public tools over a gated operation registry.

    solar_search   find capabilities, documents, operations, resources and tasks,
                   and read one task (detail, instructions, config, status,
                   result, error, history). Read-only.
    solar_docs     read documentation, contracts, requirements and references,
                   whole or by section. Read-only.
    solar_execute  run one registered operation (see operations.py). Each
                   operation has its own closed schema, authority and approval.

Resources stay open and unchanged: `resources/list` and `resources/read` are
projections of what Solar already knows.

Every `solar_execute` call goes through `mcp_gate.preflight` for the *operation*
first, and a refusal is produced by this handler, not by the caller's manners.
Task operations write only through solar-state; a runtime whose format is not
sqlite is refused. Nothing here edits, schedules or archives a task into the
queue: only `task.approve` queues, and only for the exact stored task it names.

Speaks JSON-RPC 2.0 over stdio (MCP): `initialize`, `resources/list`,
`resources/read`, `tools/list`, `tools/call`, `ping`.

    python3 mcp_server.py            # serve on stdio

The installation credentials Solar sends with no longer live in the workspace:
`solar_secrets` holds them in a 0600 file outside every tree an IDE indexes, and
`telegram.send` is the route an agent has to Telegram. That closes the
mediated path, not the machine — a process running as the user can still read
that file, and a browser session already logged in is not covered at all.
"""
from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
import uuid
from collections import deque
from functools import partial
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_context  # noqa: E402  (also puts solar-paths and solar-state on sys.path)
import mcp_gate  # noqa: E402
import runtime_views  # noqa: E402
import approval_text  # noqa: E402
import capability_registry  # noqa: E402
import docs_registry  # noqa: E402
import op_schema  # noqa: E402
import operations  # noqa: E402
import task_views  # noqa: E402
import transport_pulse  # noqa: E402
from mcp_context import OperationError, WorkspaceUnresolved, action_skills, workspace  # noqa: E402
from mcp_gate import A0, A2  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = dict(name="solar-mcp", version="0.2.0")

_SCOPES = ["capabilities", "docs", "operations", "resources", "tasks"]
_VIEWS = list(task_views._VIEWS)
_ID = {"type": "string", "minLength": 1, "maxLength": 200}

TOOLS = {
    "solar_search": dict(
        description=(
            "Find things and read task state. Read-only; grants no authority. "
            "scope=capabilities: instruction skills (query, limit, preferred_namespace). "
            "scope=docs: framework documents. "
            "scope=operations: what solar_execute can run, with authority and summary. "
            "scope=resources: the open solar:// resources (uri reads one). "
            "scope=tasks: list/filter tasks (query, state, limit), or one task with task_id and "
            "view=detail|instructions|config|status|result|error|history (default detail). "
            "Task reads return row_version, which mutating operations require."),
        inputSchema=dict(type="object", properties=dict(
            scope=dict(type="string", enum=_SCOPES),
            query=dict(type="string", maxLength=512),
            limit=dict(type="integer", minimum=1, maximum=50),
            preferred_namespace=dict(type="string", maxLength=80),
            state=dict(type="string", maxLength=20, description="Task status filter."),
            task_id=_ID,
            view=dict(type="string", enum=_VIEWS),
            section=dict(type="string", maxLength=200, description="Exact section title (view=instructions)."),
            uri=dict(type="string", maxLength=100)),
            required=["scope"], additionalProperties=False)),
    "solar_docs": dict(
        description=(
            "Read documentation, contracts, requirements and references. Read-only; instructions "
            "are not executed. id is a skill ID (optionally with a registered reference), "
            "core-doc:<name> (find with solar_search scope=docs) or operation:<name> (the contract "
            "of a solar_execute operation). Large units return an outline: request only what you "
            "need with section=\"<exact title>\"; full=true costs many more tokens. "
            "Supply the revision from search; a stale one is refused."),
        inputSchema=dict(type="object", properties=dict(
            id=_ID,
            revision=dict(type="string", maxLength=100, description="Revision from search. A stale value is refused."),
            reference=dict(type="string", maxLength=200, description="Registered Markdown reference key. Not a path."),
            section=dict(type="string", maxLength=200, description="Exact section title from the outline."),
            full=dict(type="boolean", description="Complete body; costs many more tokens.")),
            required=["id"], additionalProperties=False)),
    "solar_execute": dict(
        description=(
            "Run one registered operation: task.create, task.update, task.schedule, task.approve, "
            "task.authorize_run, task.return_to_draft, task.cancel, task.requeue, task.wait, "
            "task.archive, async_execution.propose, async_execution.apply, telegram.send, action.run. "
            "Each has its own "
            "strict arguments, authority and approval; see solar_docs id=operation:<name>. "
            "Task lifecycle operations run on the client's own tool permission (no form). "
            "task.authorize_run, async_execution.* and telegram.send ask the user for native confirmation "
            "of this exact operation and arguments: omit approval_id. Editing or scheduling never queues "
            "a task; only task.approve or task.create with queue true does, and a task the executor does "
            "not confine then waits for task.authorize_run. To ask another AI client a question, use "
            "task.create with ask, or with a declared read (access_policy mode read) plus provider and "
            "instructions; either asks the client for its read-only mode, and any other task is not one. Provider is codex, claude, agy (Antigravity) or "
            "agent (Cursor); the prompt goes in instructions; ask takes an optional folder (it starts "
            "there) and model; queue true. Send provider and instructions in the same call; ask cannot be mixed with "
            "review or review_batch (review_input_invalid). Then task.wait for its text. A question "
            "runs alone, one at a time, and a folder or a declared path outside the workspace waits for "
            "task.authorize_run. See solar_docs id=operation:task.create."),
        inputSchema=dict(type="object", properties=dict(
            operation=dict(type="string", enum=list(operations.OPERATIONS)),
            arguments=dict(type="object", description="Exactly the arguments of that operation."),
            approval_id=dict(type="string", description="Internal: set by the runtime after confirmation; omit.")),
            required=["operation", "arguments"], additionalProperties=False)),
}

# Read tools pass the same gate as operations; their authority is A0.
READ_SPEC = dict(authority=A0, description="read-only")

# Clients that cached the previous catalog get a loud, non-executing answer for
# a bounded transition (see core/docs/mcp-tool-migration.md), never a silent success
# and never a second public catalog.
LEGACY_TOOLS = {
    "solar_capability_search": ("solar_search", dict(scope="capabilities")),
    "solar_capability_describe": ("solar_docs", {}),
    "solar_task_status": ("solar_search", dict(scope="tasks")),
    "solar_task_create": ("solar_execute", dict(operation="task.create")),
    "solar_task_approve": ("solar_execute", dict(operation="task.approve")),
    "solar_task_cancel": ("solar_execute", dict(operation="task.cancel")),
    "solar_task_requeue": ("solar_execute", dict(operation="task.requeue")),
    "solar_telegram_send": ("solar_execute", dict(operation="telegram.send")),
    "solar_action_run": ("solar_execute", dict(operation="action.run")),
}
MIGRATION_DOC = "core-doc:mcp-tool-migration"

RESOURCES = [
    dict(uri="solar://health", name="Solar health",
         description="Storage, gateway and continuity as the console sees them.",
         mimeType="application/json"),
    dict(uri="solar://tasks", name="Async task queue",
         description="Every task file, by state, with its recurrence.",
         mimeType="application/json"),
    dict(uri="solar://index", name="State counts",
         description="Counts from the views in state.sqlite.",
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
    snapshot = runtime_views.snapshot(workspace())
    return dict(status=snapshot["health"]["status"], counts=snapshot["counts"],
                components=[dict(component=row["component"], state=row["state"])
                            for row in snapshot["health"]["components"]])


def _read_tasks() -> dict:
    tasks, problems = runtime_views.read_tasks(workspace())
    return dict(count=len(tasks), problems=len(problems), tasks=[
        dict(id=row["id"], title=row["title"], state=row["state"],
             recurring=row["recurring"], recurring_run_count=row["recurring_run_count"],
             recurring_last_run=row["recurring_last_run"], file=row["file"])
        for row in tasks])


def _read_index() -> dict:
    import solar_state
    try:
        snap = runtime_views.snapshot(workspace())
    except WorkspaceUnresolved:
        raise
    except Exception as exc:  # noqa: BLE001 — an unreadable state is data, not an MCP failure
        return dict(available=False, source="state", reason=str(exc))
    return dict(available=True, source="state", path=str(solar_state.db_path()),
                counts=snap["counts"])


def _read_delegations() -> dict:
    import mandates as mandate_store
    root = mandate_store.mandate_dir()
    try:
        paths = mandate_store.list_mandates()
    except OSError:
        return dict(root=str(root), mandates=[], readable=False)
    rows = []
    for path in paths:
        fields = {}
        for line in mandate_store.read_text(path).splitlines():
            key, sep, value = line.strip().partition(":")
            if sep and key in ("name", "mode", "valid_from", "expires_at"):
                fields.setdefault(key, value.strip().strip('"').strip("'"))
        rows.append(dict(file=path.name, **fields))
    return dict(root=str(root), readable=True, mandates=rows)


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
# solar_search / solar_docs
# --------------------------------------------------------------------------

_SEARCH_KEYS = {
    "capabilities": {"scope", "query", "limit", "preferred_namespace"},
    "docs": {"scope", "query", "limit"},
    "operations": {"scope", "query", "limit"},
    "resources": {"scope", "uri"},
    "tasks": {"scope", "query", "limit", "state", "task_id", "view", "section"},
}
_TASK_LIST_KEYS = {"query", "limit", "state"}
_TASK_ONE_KEYS = {"task_id", "view", "section"}


def _search_problem(arguments: dict) -> str | None:
    """Per-scope closure: a scope accepts only the keys it uses."""
    scope = arguments["scope"]
    extra = set(arguments) - _SEARCH_KEYS[scope]
    if extra:
        return f"arguments.{sorted(extra)[0]}: not accepted with scope={scope}"
    if scope == "capabilities" and "query" not in arguments:
        return "arguments.query: required with scope=capabilities"
    if scope == "tasks":
        if "task_id" in arguments and set(arguments) & _TASK_LIST_KEYS:
            return "arguments: task_id reads one task; query, limit and state list tasks"
        if "task_id" not in arguments and set(arguments) & {"view", "section"}:
            return "arguments: view and section need task_id"
    return None


def _do_search(arguments: dict) -> dict:
    scope = arguments["scope"]
    if scope == "capabilities":
        return capability_registry.search(arguments["query"], arguments.get("limit", 5),
                                          arguments.get("preferred_namespace", ""))
    if scope == "docs":
        return docs_registry.search_docs(arguments.get("query", ""), arguments.get("limit", 10))
    if scope == "operations":
        terms = set(re.findall(r"\w+", arguments.get("query", "").casefold()))
        rows = [dict(name=op.name, authority=op.authority, summary=op.summary,
                     external_communication=op.external_communication)
                for op in operations.OPERATIONS.values()
                if not terms or terms & set(re.findall(
                    r"\w+", f"{op.name} {op.summary}".casefold()))]
        return dict(operations=rows[:arguments.get("limit", 50)],
                    contract="solar_docs id=operation:<name>",
                    call="solar_execute operation=<name> arguments={...}")
    if scope == "resources":
        uri = arguments.get("uri")
        if not uri:
            return dict(resources=RESOURCES)
        reader = READERS.get(uri)
        if reader is None:
            raise OperationError("unknown_resource",
                                 f"Unknown resource: {uri}. Known: {', '.join(READERS)}")
        return dict(uri=uri, contents=reader())
    if "task_id" in arguments:
        return task_views.view_task(arguments["task_id"], arguments.get("view", "detail"),
                                    arguments.get("section", ""))
    return task_views.find_tasks(arguments.get("query", ""), arguments.get("state", ""),
                                 arguments.get("limit", 10))


def _do_docs(arguments: dict) -> dict:
    try:
        return docs_registry.read(**arguments)
    except ValueError as exc:
        raise OperationError("docs_refused", str(exc)) from None


READ_HANDLERS = {"solar_search": _do_search, "solar_docs": _do_docs}


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def resolve_execute(arguments: dict):
    """Validate a solar_execute call: (operation, inner arguments, problem)."""
    # The envelope is closed; the nested `arguments` object is validated against
    # the operation's own schema below, never against a generic one.
    schema = TOOLS["solar_execute"]["inputSchema"]
    shell = dict(schema, required=[k for k in schema["required"] if k != "arguments"],
                 properties={k: v for k, v in schema["properties"].items() if k != "arguments"})
    problem = op_schema.check({k: v for k, v in arguments.items() if k != "arguments"}, shell, "arguments")
    if not problem and not isinstance(arguments.get("arguments"), dict):
        problem = "arguments.arguments: expected object"
    if problem:
        return None, {}, problem
    op = operations.OPERATIONS[arguments["operation"]]
    inner = arguments["arguments"]
    problem = op_schema.check(inner, op.schema, f"arguments.{op.name}")
    return (None, {}, problem) if problem else (op, inner, None)


def _legacy_answer(name: str) -> dict:
    tool, template = LEGACY_TOOLS[name]
    return dict(
        error=(f"{name} no longer exists. Use {tool}"
               + (f" with operation={template['operation']}" if "operation" in template else "")
               + ". This answer is a transition notice: nothing was executed."),
        code="tool_renamed", legacy_tool=name,
        replacement=dict(tool=tool, **{k: v for k, v in template.items()}),
        migration=dict(tool="solar_docs", arguments=dict(id=MIGRATION_DOC)),
        executed=False)


def call_tool(name: str, arguments: dict) -> tuple[dict, bool]:
    """Gate first, then act. There is no path to a handler that skips this."""
    arguments = arguments if isinstance(arguments, dict) else {}
    trace = uuid.uuid4().hex[:12]
    if name in LEGACY_TOOLS:
        verdict = mcp_gate.Verdict(False, "tool_renamed",
                                   f"{name} was replaced by {LEGACY_TOOLS[name][0]}", A0, name)
        mcp_gate.record(verdict, arguments, trace, via=name)
        return dict(_legacy_answer(name), trace_id=trace, verdict=verdict.as_dict()), True
    if name not in TOOLS:
        verdict = mcp_gate.preflight(name, arguments, {})
        mcp_gate.record(verdict, arguments, trace, via=name)
        return dict(refused=verdict.as_dict(), trace_id=trace), True
    try:
        workspace()
    except WorkspaceUnresolved as exc:
        return dict(error=str(exc)[:500], code="workspace_unresolved", trace_id=trace), True

    if name == "solar_execute":
        op, inner, problem = resolve_execute(arguments)
        if problem:
            return dict(error=f"Invalid tool arguments: {problem}", code="invalid_arguments",
                        trace_id=trace), True
        gate_name, gate_args = op.name, dict(inner)
        if arguments.get("approval_id"):
            gate_args["approval_id"] = arguments["approval_id"]
        registry = {op.name: op.gate_spec(), "_action_skills": action_skills()}
    else:
        problem = op_schema.check(arguments, TOOLS[name]["inputSchema"], "arguments")
        if not problem and name == "solar_search":
            problem = _search_problem(arguments)
        if problem:
            return dict(error=f"Invalid tool arguments: {problem}", code="invalid_arguments",
                        trace_id=trace), True
        op, gate_name, gate_args = None, name, arguments
        registry = {name: READ_SPEC}

    with mcp_gate.execution_lock(gate_name, registry):
        verdict = mcp_gate.preflight(gate_name, gate_args, registry)
        mcp_gate.record(verdict, gate_args, trace, via=name)
        if not verdict.allowed:
            return dict(refused=verdict.as_dict(), operation=gate_name, trace_id=trace), True
        # Reserve before side effects: an uncertain failure must not be replayed.
        mcp_gate.consume(gate_name, gate_args, registry)
    handler = operations.HANDLERS[op.name] if op else READ_HANDLERS[name]
    try:
        result = handler(dict(inner) if op else dict(arguments))
    except Exception as exc:  # noqa: BLE001 - every failure leaves an outcome row
        code = operations.error_code(exc)
        mcp_gate.record_outcome(gate_name, trace, False, code, str(exc))
        return dict(error=str(exc)[:500], code=code, operation=gate_name, trace_id=trace,
                    verdict=verdict.as_dict()), True
    mcp_gate.record_outcome(gate_name, trace, True, "ok")
    payload = dict(result=result, verdict=verdict.as_dict(), trace_id=trace)
    if op:
        payload["operation"] = op.name
    return payload, False


# --------------------------------------------------------------------------
# JSON-RPC over stdio
# --------------------------------------------------------------------------

def _text(payload) -> list:
    return [dict(type="text", text=json.dumps(payload, indent=2, sort_keys=True, default=str))]


def _confirmation_content(content, confirmation: dict):
    """Add server-owned diagnostics only to a supported content envelope."""
    if (not isinstance(content, list) or len(content) != 1 or
            not isinstance(content[0], dict) or content[0].get('type') != 'text'):
        return content
    try:
        payload = json.loads(content[0].get('text'))
        if not isinstance(payload, dict):
            return content
        diagnostic = dict(confirmation)
        refused = payload.get('refused')
        if (not diagnostic['client_form_advertised'] and isinstance(refused, dict) and
                refused.get('code') == 'approval_required'):
            diagnostic.update(reason='client_form_not_advertised', recovery=(
                'This connection did not advertise MCP form elicitation. '
                'Native question tools are separate and cannot grant Solar approval by themselves. '
                'Use a form-capable client or a verified host adapter; do not self-grant or retry unchanged.'))
        # Reserved at envelope level; a handler's result stays nested under result.
        payload['confirmation'] = diagnostic
        return [dict(content[0], text=_text(payload)[0]['text'])]
    except (ValueError, TypeError):
        # Diagnostics must not replace a completed operation's original response.
        return content


def handle(message: dict, confirm=None) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        result = dict(protocolVersion=PROTOCOL_VERSION, serverInfo=SERVER_INFO,
                      capabilities=dict(resources=dict(listChanged=False), tools=dict(listChanged=False)),
                      instructions=("Three tools. solar_search finds capabilities, documents, operations, "
                                    "resources and tasks, and reads one task. solar_docs reads documentation "
                                    "and contracts by section. solar_execute runs one registered operation: "
                                    "the handler validates its strict arguments, authority and mandate and "
                                    "refuses on its own. Omit approval_id to request native client "
                                    "confirmation of that exact call. Never ask users to manage IDs or "
                                    "self-grant through shell. Editing or scheduling a task never queues "
                                    "it. Clients without elicitation need a trusted host/operator approval path."))
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
            known = ", ".join(READERS)
            return _error(request_id, -32602,
                          f"Unknown resource: {uri}. Known: {known}")
        try:
            body = reader()
        except WorkspaceUnresolved as exc:
            return _error(request_id, -32000, str(exc))
        result = dict(contents=[dict(uri=uri, mimeType="application/json",
                                     text=json.dumps(body, indent=2, sort_keys=True, default=str))])
    elif method == "tools/list":
        result = dict(tools=[dict(name=name, description=spec["description"],
                                  inputSchema=spec["inputSchema"])
                             for name, spec in TOOLS.items()])
    elif method == "tools/call":
        name = params.get("name", "")
        arguments = dict(params.get("arguments") or {})
        if confirm and name == "solar_execute" and not arguments.get("approval_id"):
            # Only the transport callback receives client UI responses. No tool
            # parameter or caller-supplied approved flag can grant authority.
            op, inner, problem = resolve_execute(arguments)
            if problem:
                return _error(request_id, -32602, f"Invalid tool arguments: {problem}")
            if op.authority == A2 and not op.client_consent:
                if op.pre_confirm:
                    try:
                        op.pre_confirm(inner)
                    except OperationError as exc:
                        return _error(request_id, -32602, str(exc))
                if confirm(op.name, inner, request_id):
                    import mcp_approve
                    granted = mcp_approve.grant(op.name, inner, CONFIRMATION_TIMEOUT, "client elicitation: explicit confirmation")
                    arguments["approval_id"] = granted["approval_id"]
        payload, is_error = call_tool(name, arguments)
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


class ConfirmationCancelled(Exception):
    """The client cancelled the originating request; send no response."""


CONFIRMATION_TIMEOUT = 120


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    incoming = queue.Queue()
    def read_lines():
        for line in stdin:
            incoming.put(line)
        incoming.put(None)
    threading.Thread(target=read_lines, daemon=True).start()
    supports_confirmation = False
    confirmation = dict(client_form_advertised=False, transport='unavailable',
                        attempted=False, outcome='not_requested')
    deferred = deque()
    cancelled = set()
    active_key = None

    def request_key(value):
        return (type(value).__name__, value)

    def remember_cancel(message):
        if message.get("method") == "notifications/cancelled":
            value = (message.get("params") or {}).get("requestId")
            if isinstance(value, (str, int)):
                key = request_key(value)
                # Only live requests can be cancelled. A late/unknown ID must
                # not poison a future request that legitimately reuses it.
                pending = (json.loads(raw) for raw in deferred)
                if key == active_key or any(
                    'method' in item and 'id' in item and request_key(item['id']) == key
                    for item in pending
                ):
                    cancelled.add(key)
            return True
        return False

    def emit(message):
        stdout.write(json.dumps(message, default=str) + "\n")
        stdout.flush()

    def confirm(name, arguments, request_id, *, request_meta=None):
        # The text is rendered here from the validated arguments and the stored
        # task, never from caller prose; the binding stays on the full arguments.
        elicitation_id = 'approval-' + uuid.uuid4().hex
        message, checkbox = approval_text.render(name, arguments, seconds=CONFIRMATION_TIMEOUT)
        form_params = dict(
            message=message,
            requestedSchema=dict(type="object", properties=dict(
                approve=dict(type="boolean", title=checkbox, default=False)), required=["approve"]))
        # Some hosts route native forms using the originating progress token.
        # Correlation is not authority; never forward other caller metadata.
        token = request_meta.get('progressToken') if isinstance(request_meta, dict) else None
        if type(token) in (str, int):
            form_params['_meta'] = {'progressToken': token}
        emit(dict(jsonrpc="2.0", id=elicitation_id, method="elicitation/create", params=form_params))
        def close_form():
            emit(dict(jsonrpc="2.0", method="notifications/cancelled",
                      params=dict(requestId=elicitation_id, reason="Origin cancelled or confirmation expired")))
        deadline = time.monotonic() + CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            try:
                raw = incoming.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                close_form()
                return False
            if raw is None:
                incoming.put(None)
                return False
            try:
                response = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(response, dict):
                continue
            if response.get('id') == elicitation_id and 'method' not in response:
                result = response.get('result') or {}
                if not isinstance(result, dict) or not isinstance(result.get('content', {}), dict):
                    return False
                return (not response.get('error') and result.get('action') == 'accept'
                        and (result.get('content') or {}).get('approve') is True)
            if remember_cancel(response):
                target = (response.get('params') or {}).get('requestId')
                if request_key(target) == request_key(request_id):
                    close_form()
                    raise ConfirmationCancelled()
                if target == elicitation_id:
                    cancelled.discard(request_key(target))
                    return False
                continue
            if response.get('method') == 'ping':
                if 'id' in response:
                    emit(dict(jsonrpc="2.0", id=response['id'], result={}))
            elif 'method' in response:
                deferred.append(raw)
        close_form()
        return False

    def confirm_and_record(name, arguments, request_id, *, request_meta=None):
        confirmation.update(attempted=True, outcome='pending')
        try:
            accepted = confirm(name, arguments, request_id, request_meta=request_meta)
        except ConfirmationCancelled:
            confirmation['outcome'] = 'cancelled'
            raise
        confirmation['outcome'] = 'accepted' if accepted else 'not_accepted'
        return accepted

    while True:
        line = deferred.popleft() if deferred else incoming.get()
        if line is None:
            break
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError('object expected')
        except ValueError:
            emit(_error(None, -32700, "Parse error"))
            continue
        # Ignore unmatched responses; they cannot authorize future calls.
        if 'method' not in message:
            continue
        if remember_cancel(message):
            continue
        if request_key(message.get('id')) in cancelled:
            cancelled.discard(request_key(message.get('id')))
            continue
        if message.get('method') == 'initialize':
            capabilities = (message.get('params') or {}).get('capabilities') or {}
            elicitation = capabilities.get('elicitation') if isinstance(capabilities, dict) else None
            supports_confirmation = (isinstance(elicitation, dict) and
                                     (not elicitation or isinstance(elicitation.get('form'), dict)))
            confirmation.update(client_form_advertised=supports_confirmation,
                                transport='mcp-form' if supports_confirmation else 'unavailable')
        active_key = request_key(message['id']) if 'id' in message else None
        try:
            confirmation.update(attempted=False, outcome='not_requested')
            params = message.get('params')
            request_meta = params.get('_meta') if isinstance(params, dict) else None
            callback = partial(confirm_and_record, request_meta=request_meta) if supports_confirmation else None

            def drain(seconds: float) -> bool:
                """Answer the transport while a long read-only handler sleeps:
                a `ping` gets its reply now and a cancellation of the live
                request ends the wait. Anything else goes to `deferred`, where
                `remember_cancel` can see it too; nothing is requeued to
                `incoming`, so no message loses its place and no slice spins.
                Returns False only when the caller's request was cancelled (or
                the stream closed)."""
                deadline = time.monotonic() + seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return True
                    try:
                        raw = incoming.get(timeout=remaining)
                    except queue.Empty:
                        return True
                    if raw is None:
                        incoming.put(None)
                        return False
                    try:
                        response = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(response, dict):
                        continue
                    if remember_cancel(response):
                        target = (response.get('params') or {}).get('requestId')
                        if request_key(target) == active_key:
                            return False
                        continue
                    if response.get('method') == 'ping':
                        if 'id' in response:
                            emit(dict(jsonrpc="2.0", id=response['id'], result={}))
                        continue
                    deferred.append(raw)
            if active_key is not None and message.get('method') == 'tools/call':
                transport_pulse.install(drain)
            response = handle(message, callback)
            if response and 'result' in response:
                if message.get('method') == 'initialize':
                    response['result']['_meta'] = {'solar/confirmation': dict(confirmation)}
                elif (message.get('method') == 'tools/call' and
                      (message.get('params') or {}).get('name') == 'solar_execute'):
                    result = response['result']
                    if isinstance(result, dict) and 'content' in result:
                        result['content'] = _confirmation_content(result['content'], confirmation)
        except ConfirmationCancelled:
            cancelled.discard(request_key(message.get('id')))
            continue
        except Exception as exc:
            response = _error(message.get("id"), -32603, str(exc)[:300])
        finally:
            transport_pulse.clear()
            active_key = None
        if response is not None:
            emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
