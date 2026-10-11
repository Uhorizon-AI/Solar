"""The registry behind `solar_execute`.

An operation is an explicit, named verb with its own authority level and its own
closed argument schema. There is no operation that takes a command, a path or a
query: what can run is exactly what is registered here, nothing is inferred from
a skill, and an instruction skill never becomes an operation.

Authority, approval and the audit trail are applied per operation, not per
tool: an approval names one operation and its exact arguments, so grouping
verbs behind one public tool widens nothing.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_context  # noqa: E402
import task_views  # noqa: E402
from mcp_context import OperationError, workspace  # noqa: E402
from mcp_gate import A2, A3  # noqa: E402

_SKILLS = mcp_context._SKILLS

TASK_ID = {"type": "string", "minLength": 1, "maxLength": 200,
           "pattern": r"(?!\.{1,2}$)[^/\\\x00-\x1f\x7f]+"}
ROW_VERSION = {"type": "integer", "minimum": 1,
               "description": "row_version read from solar_search; a stale value is refused."}
SLUG = {"type": "string", "minLength": 1, "maxLength": 80, "pattern": r"[A-Za-z0-9][A-Za-z0-9._:-]*"}
LINE = lambda limit: {"type": "string", "minLength": 1, "maxLength": limit,  # noqa: E731
                       "pattern": r"[^\x00-\x1f\x7f]+"}   # one line, no control characters


@dataclass(frozen=True)
class Operation:
    name: str
    authority: str
    summary: str
    schema: dict
    errors: tuple = ()
    external_communication: bool = False
    refuses_mandate: bool = False
    effects: str = ""
    # Extra rule checked on the arguments before an approval is requested.
    pre_confirm: Optional[Callable[[dict], None]] = field(default=None, compare=False)

    def gate_spec(self) -> dict:
        spec = dict(authority=self.authority, description=self.summary)
        if self.external_communication:
            spec["external_communication"] = True
        if self.refuses_mandate:
            spec["refuses_mandate"] = True
        return spec


def _obj(properties: dict, required=()) -> dict:
    return dict(type="object", properties=properties, required=list(required),
                additionalProperties=False)


# ---------------------------------------------------------------------------
# task handlers
# ---------------------------------------------------------------------------

# Copied into a revision so that it keeps the source's execution restrictions
# (origin_channel: app/voice run read-only), notification destination and resource
# hooks. Origin request/thread/run ids are deliberately not copied: they identify
# one request, and the queue de-duplicates on them.
_COPIED = ("priority", "provider", "planet", "agent", "responsibility", "agent_contract",
           "object", "scope", "effect", "notify_when", "origin_channel", "origin_chat_id",
           "resources", "cleanup_required", "cleanup_timeout",
           "scheduled_time", "scheduled_weekdays", "scheduled_timezone", "recurring",
           "recurring_min_interval", "recurring_max_runs")
_TEXT_FIELDS = ("title", "object", "scope", "effect", "provider", "planet", "agent",
                "responsibility")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _actor(operation: str) -> str:
    return f"mcp:{operation}"


def _fm(value) -> str:
    """The one way a value is written into frontmatter: JSON strings, bare booleans and integers."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _body(title: str, instructions: str) -> str:
    return f"\n# {title}\n\n{instructions.rstrip()}\n"


def _task(store, task_id: str) -> dict:
    task = store.task_get(task_id)
    if task is None:
        raise OperationError("task_not_found", f"no task {task_id}")
    return task


def _do_task_create(arguments: dict) -> dict:
    import solar_state

    fields = [("title", json.dumps(arguments["title"], ensure_ascii=False)),
              ("created", json.dumps(_now_iso())),
              ("updated", json.dumps(_now_iso()))]
    source_id = arguments.get("revises_task_id")
    copied: dict = {}
    with solar_state.session() as store:
        if source_id:
            source = _task(store, source_id)
            raw = {key: rest for key, rest in source["frontmatter"]}
            if "executor" in raw or "local_command" in raw:
                raise OperationError(
                    "revision_unsupported",
                    "A task with a local executor is not revised through MCP: "
                    "executor settings are never copied or set here.")
            for key in _COPIED:
                if key in raw and raw[key].strip():
                    copied[key] = raw[key].strip()
        explicit = {key: json.dumps(arguments[key], ensure_ascii=False)
                    for key in _TEXT_FIELDS if key in arguments and key != "title"}
        merged = {**copied, **explicit}
        merged.setdefault("priority", "normal")
        if "priority" in arguments:
            merged["priority"] = arguments["priority"]
        fields += list(merged.items())
        if source_id:
            fields.append(("revises_task_id", json.dumps(source_id)))
            fields.append(("revises_digest", json.dumps(
                solar_state.material_digest(source["frontmatter"], source["body"]))))
        task_id = store.task_create(fields, _body(arguments["title"], arguments["instructions"]),
                                    status="draft", actor=_actor("task.create"))
        task = store.task_get(task_id)
    digest = solar_state.material_digest(task["frontmatter"], task["body"])
    result = dict(created=True, id=task_id, status="draft", row_version=task["row_version"],
                  digest=digest, activated=False,
                  next="Review it with solar_search, then approve it with task.approve.")
    if source_id:
        result["revises_task_id"] = source_id
        result["source_unchanged"] = True
    return result


def _edit(task_id: str, expected: int, fields: dict, body: Optional[str], operation: str) -> dict:
    """Shared edit path: draft or planned only, one transaction, never activates."""
    import solar_state

    with solar_state.session() as store:
        task = _task(store, task_id)
        if task["status"] == "active":
            raise OperationError(
                "task_active_immutable",
                "An active task keeps the instructions it started with. Request cancellation, "
                "wait for it to stop, then revise it with task.create and revises_task_id.")
        if task["status"] not in ("draft", "planned"):
            raise OperationError(
                "task_not_editable",
                f"{task_id} is {task['status']}. Approved or finished tasks keep what was "
                "approved; prepare a revision with task.create and revises_task_id.")
        fields = dict(fields, updated=json.dumps(_now_iso()))
        # A planned task was reviewed as it stood: any change sends it back to draft.
        result = store.task_update(
            task_id, expected_row_version=expected, allowed_status=("draft", "planned"),
            fields=fields, body=body, to_status="draft" if task["status"] == "planned" else None,
            actor=_actor(operation))
    result.update(activated=False, needs_approval=True)
    return result


def _do_task_update(arguments: dict) -> dict:
    import solar_state

    changes = {key: value for key, value in arguments.items()
               if key not in ("task_id", "expected_row_version")}
    if not changes:
        raise OperationError("no_changes", "Name at least one field to change.")
    with solar_state.read_session() as store:
        current = _task(store, arguments["task_id"])
    old_title = solar_state.value_of(dict((k, v) for k, v in current["frontmatter"]).get("title")) or ""
    fields = {key: _fm(value) for key, value in changes.items() if key in _TEXT_FIELDS}
    if "priority" in changes:
        fields["priority"] = changes["priority"]
    body = None
    title = changes.get("title", old_title)
    if "instructions" in changes:
        body = _body(title, changes["instructions"])
    elif "title" in changes:
        heading = f"\n# {old_title}\n"
        if current["body"].startswith(heading):
            body = f"\n# {title}\n" + current["body"][len(heading):]
    return _edit(arguments["task_id"], arguments["expected_row_version"], fields, body,
                 "task.update")


def _do_task_schedule(arguments: dict) -> dict:
    import solar_state

    task_id = arguments["task_id"]
    with solar_state.read_session() as store:
        current = _task(store, task_id)
    stored = {key: solar_state.value_of(rest) for key, rest in current["frontmatter"]}
    merged = dict(
        scheduled_time=arguments.get("scheduled_time", stored.get("scheduled_time")),
        scheduled_timezone=arguments.get("scheduled_timezone", stored.get("scheduled_timezone")),
        recurring=arguments.get("recurring", str(stored.get("recurring") or "").lower() == "true"),
        weekdays=arguments.get("scheduled_weekdays") if "scheduled_weekdays" in arguments
        else [int(d) for d in str(stored.get("scheduled_weekdays") or "").split(",") if d.strip().isdigit()])
    plan = task_views.plan_schedule(
        time=merged["scheduled_time"], weekdays=merged["weekdays"],
        zone=merged["scheduled_timezone"], recurring=merged["recurring"],
        min_interval=arguments.get("recurring_min_interval",
                                   int(stored["recurring_min_interval"])
                                   if str(stored.get("recurring_min_interval") or "").isdigit() else None))
    fields: dict = {}
    if "scheduled_time" in arguments:
        fields["scheduled_time"] = _fm(arguments["scheduled_time"])
    if "scheduled_weekdays" in arguments:
        fields["scheduled_weekdays"] = _fm(",".join(str(d) for d in arguments["scheduled_weekdays"]))
    if "scheduled_timezone" in arguments:
        fields["scheduled_timezone"] = _fm(arguments["scheduled_timezone"])
    if "recurring" in arguments:
        fields["recurring"] = _fm(arguments["recurring"])
    if "recurring_max_runs" in arguments:
        fields["recurring_max_runs"] = _fm(arguments["recurring_max_runs"])
    if merged["recurring"] and plan["recurring_min_interval"] is not None:
        fields["recurring_min_interval"] = _fm(plan["recurring_min_interval"])
    result = _edit(task_id, arguments["expected_row_version"], fields, None, "task.schedule")
    result["schedule"] = plan
    return result


def _do_task_approve(arguments: dict) -> dict:
    import solar_state

    task_id = arguments["task_id"]
    with solar_state.session() as store:
        came = store.task_approve(task_id, actor=_actor("task.approve"),
                                  expected_row_version=arguments["expected_row_version"])
        task = store.task_get(task_id)
    stored = {key: solar_state.value_of(rest) for key, rest in task["frontmatter"]}
    return dict(approved=True, id=task_id, from_status=came, to_status="queued",
                approved_digest=stored.get("approved_digest"), row_version=task["row_version"])


def _do_task_cancel(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        return store.task_cancel(arguments["task_id"], actor=_actor("task.cancel"),
                                 expected_row_version=arguments["expected_row_version"])


def _do_task_requeue(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        came = store.task_requeue(arguments["task_id"], actor=_actor("task.requeue"),
                                  expected_row_version=arguments["expected_row_version"])
    return dict(requeued=True, id=arguments["task_id"], from_status=came, to_status="queued")


def _do_task_archive(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        result = store.task_archive(arguments["task_id"],
                                    expected_row_version=arguments["expected_row_version"],
                                    reason=arguments["reason"], actor=_actor("task.archive"))
    return dict(result, archived=True, history_preserved=True)


# ---------------------------------------------------------------------------
# external communication and delegated actions
# ---------------------------------------------------------------------------

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


def _require_chat(arguments: dict) -> None:
    if not arguments.get("chat_id"):
        raise OperationError("chat_id_required",
                             "Supply the exact chat_id before confirming a send")


def _do_action_run(arguments: dict) -> dict:
    entry = mcp_context.action_skills().get(arguments["skill"], {})
    command = list(entry.get("command") or [])
    if not command:
        raise RuntimeError(f"{arguments['skill']} has no command registered")
    proc = subprocess.run(command + [str(arguments["action"])],
                          capture_output=True, text=True, timeout=600,
                          cwd=str(workspace()))
    return dict(exit_code=proc.returncode,
                stdout=(proc.stdout or "").strip()[:2000],
                stderr=(proc.stderr or "").strip()[:1000])


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

_TITLE = LINE(200)
_INSTRUCTIONS = {"type": "string", "minLength": 1, "maxLength": 60000}
_PRIORITY = {"type": "string", "enum": ["low", "normal", "high"]}
_WEEKDAY = {"type": "integer", "minimum": 1, "maximum": 7}
_TIME = {"type": "string", "maxLength": 5, "pattern": r"([01]\d|2[0-3]):[0-5]\d",
         "description": "24-hour HH:MM, read in scheduled_timezone."}
_ZONE = {"type": "string", "minLength": 3, "maxLength": 64, "pattern": r"[A-Za-z0-9_+/-]+",
         "description": "IANA zone, e.g. Europe/Madrid."}
_APPROVED_ONLY = "Does not queue or run anything."

OPERATIONS: dict[str, Operation] = {op.name: op for op in (
    Operation(
        "task.create", A2, "Create a draft task, or a draft revision of an existing task.",
        _obj(dict(title=_TITLE, instructions=_INSTRUCTIONS, object=LINE(500), scope=LINE(500),
                  effect=LINE(500), priority=_PRIORITY, provider=SLUG, planet=SLUG, agent=SLUG,
                  responsibility=SLUG, revises_task_id=TASK_ID),
             required=("title", "instructions")),
        errors=("task_not_found", "revision_unsupported"),
        effects="Writes one draft row. " + _APPROVED_ONLY + " revises_task_id copies "
                "configuration and schedule from that task and leaves it untouched."),
    Operation(
        "task.update", A2, "Edit the content of a draft or planned task.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION, title=_TITLE,
                  instructions=_INSTRUCTIONS, object=LINE(500), scope=LINE(500), effect=LINE(500),
                  priority=_PRIORITY, provider=SLUG, planet=SLUG, agent=SLUG,
                  responsibility=SLUG), required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_active_immutable", "task_not_editable",
                "no_changes"),
        effects="Rewrites the draft. A planned task returns to draft. " + _APPROVED_ONLY),
    Operation(
        "task.schedule", A2, "Set the schedule and recurrence of a draft or planned task.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION, scheduled_time=_TIME,
                  scheduled_weekdays={"type": "array", "items": _WEEKDAY, "minItems": 1,
                                      "maxItems": 7, "uniqueItems": True},
                  scheduled_timezone=_ZONE, recurring={"type": "boolean"},
                  recurring_min_interval={"type": "integer", "minimum": 3600,
                                          "maximum": 31536000},
                  recurring_max_runs={"type": "integer", "minimum": 0, "maximum": 10000}),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_active_immutable", "task_not_editable",
                "no_changes", "schedule_invalid"),
        effects="Stores the schedule. " + _APPROVED_ONLY),
    Operation(
        "task.approve", A2, "Move a draft or planned task to the queue.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        refuses_mandate=True,
        effects="Queues the task as it is stored now; a later edit invalidates this approval. "
                "Refuses a revision while the task it replaces can still run."),
    Operation(
        "task.cancel", A2, "Cancel a queued task, or request cancellation of an active one.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        effects="A queued task becomes cancelled; an active one stays active until the worker stops."),
    Operation(
        "task.requeue", A2, "Move a task from error back to the queue.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        effects="Drops the recorded execution error; instructions are unchanged."),
    Operation(
        "task.archive", A2, "Archive a task, keeping its row, events and body.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION, reason=LINE(300)),
             required=("task_id", "expected_row_version", "reason")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        effects="A queued task, a recurrence waiting for its next run included, is cancelled and "
                "archived in one step. Refused while the task is active, while another task waits "
                "on it, or while its subtasks run."),
    Operation(
        "telegram.send", A2, "Send one Telegram message as the Solar runtime.",
        _obj(dict(text={"type": "string", "minLength": 1, "maxLength": 4096},
                  chat_id={"type": "string", "maxLength": 33, "pattern": r"-?\d{1,20}|@[A-Za-z0-9_]{5,32}"},
                  parse_mode={"type": "string", "enum": ["Markdown", "HTML"]}),
             required=("text", "chat_id")),
        errors=("chat_id_required", "operation_failed"),
        external_communication=True, pre_confirm=_require_chat,
        effects="Sends outside the machine. The approval covers this exact text and chat."),
    Operation(
        "action.run", A3, "Run one registered action of one registered action skill under a live mandate.",
        _obj(dict(skill=SLUG, action=SLUG, mandate=SLUG, automated={"type": "boolean"}),
             required=("skill", "action")),
        errors=("skill_not_registered", "action_not_allowed", "mandate_denied", "mandate_mismatch"),
        effects="Runs the command registered for that skill. Instruction skills are not reachable."),
)}

HANDLERS: dict[str, Callable[[dict], dict]] = {
    "task.create": _do_task_create,
    "task.update": _do_task_update,
    "task.schedule": _do_task_schedule,
    "task.approve": _do_task_approve,
    "task.cancel": _do_task_cancel,
    "task.requeue": _do_task_requeue,
    "task.archive": _do_task_archive,
    "telegram.send": _do_telegram_send,
    "action.run": _do_action_run,
}


def error_code(exc: Exception) -> str:
    """Stable code for a failure; the message stays human."""
    import solar_state

    if isinstance(exc, OperationError):
        return exc.code
    if isinstance(exc, solar_state.TaskChanged):
        return "task_changed"
    if isinstance(exc, solar_state.TransitionRefused):
        return "task_state_refused"
    if isinstance(exc, solar_state.StateUnavailable):
        return "state_unavailable"
    if isinstance(exc, solar_state.StateError):
        return "state_refused"
    return "operation_failed"
