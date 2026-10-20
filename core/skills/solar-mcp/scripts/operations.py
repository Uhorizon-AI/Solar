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
from mcp_gate import A0, A2, A3  # noqa: E402

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
    # The client's own tool permission is the consent: no native form. Only for local operations whose
    # worst outcome is a task that still needs `task.authorize_run` before anything risky runs.
    client_consent: bool = False
    effects: str = ""
    # Extra rule checked on the arguments before an approval is requested.
    pre_confirm: Optional[Callable[[dict], None]] = field(default=None, compare=False)

    def gate_spec(self) -> dict:
        spec = dict(authority=self.authority, description=self.summary)
        if self.external_communication:
            spec["external_communication"] = True
        if self.refuses_mandate:
            spec["refuses_mandate"] = True
        if self.client_consent:
            spec["client_consent"] = True
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
           "recurring_min_interval", "recurring_max_runs",
           # What a revision may touch stays what its source declared; evidence digests do not carry over.
           "access_policy", "execution_profile")
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


def _access_text(declared: dict) -> str:
    """The canonical stored spelling of an access declaration, or a refusal that says why."""
    import solar_state

    try:
        return solar_state.canonical_policy_text("access_policy", dict(declared, version=1))
    except solar_state.FormatError as exc:
        raise OperationError("access_policy_invalid", str(exc)) from None


def _body(title: str, instructions: str) -> str:
    return f"\n# {title}\n\n{instructions.rstrip()}\n"


def _task(store, task_id: str) -> dict:
    task = store.task_get(task_id)
    if task is None:
        raise OperationError("task_not_found", f"no task {task_id}")
    return task


def _review_fields(arguments: dict) -> dict:
    """Compose inputs through Router before native confirmation; never queue."""
    if "review_batch" in arguments:
        return _review_batch_fields(arguments)
    if "review" not in arguments:
        return {}
    router_scripts = str(_SKILLS / "solar-router" / "scripts")
    if router_scripts not in sys.path:
        sys.path.insert(0, router_scripts)
    from execution_profiles import build_review_envelope_v1, verify_sources, canonical, ProfileError
    from repository_reviews import build as build_repository, PROFILE as REPOSITORY_PROFILE
    spec = arguments["review"]
    try:
        if not arguments.get("provider") or not arguments.get("instructions"):
            raise OperationError("review_input_invalid", "A review needs explicit provider and instructions.")
        common = dict(provider=arguments["provider"], model=spec["model"],
                      instructions=arguments["instructions"], rules=spec.get("rules", []))
        if spec["profile"] == REPOSITORY_PROFILE:
            if set(spec) - {"profile", "model", "rules", "repository", "commit"}:
                raise OperationError("review_input_invalid", "Repository reviews cannot contain packet evidence.")
            envelope = build_repository(repository=spec["repository"], commit=spec["commit"], **common)
            scopes = [spec["repository"]]
        else:
            if set(spec) - {"profile", "model", "rules", "evidence"}:
                raise OperationError("review_input_invalid", "Packet reviews cannot contain repository fields.")
            envelope = build_review_envelope_v1(evidence=[dict(path=e["source_path"], content=e["content"], sha256=e["sha256"]) for e in spec["evidence"]], **common)
            scopes = [item["source_path"] for item in spec["evidence"]]
        access = arguments.get("access_policy", dict(mode="read", scopes=scopes, resources=[]))
        if access["mode"] != "read":
            raise OperationError("review_input_invalid", "Review access must be read-only.")
        verify_sources(envelope["manifest"], access.get("scopes", []))
        return dict(execution_profile=json.dumps(spec["profile"]),
                    review_input_manifest=json.dumps(canonical(envelope["manifest"])),
                    review_input_digest=json.dumps(envelope["review_input_digest"]),
                    access_policy=_access_text(access))
    except (ProfileError, KeyError, ValueError, TypeError) as exc:
        raise OperationError("review_input_invalid", getattr(exc, "code", "Review fields are incomplete.")) from None


def _review_batch_fields(arguments):
    if "review" in arguments or any(not arguments.get(k) for k in ("object", "scope", "effect")):
        raise OperationError("review_input_invalid", "A review batch needs object/scope/effect and no single review.")
    spec = arguments["review_batch"]
    entries, templates, declarations = [], [], []
    keys, titles = set(), set()
    repository = spec["repository"]
    for child in spec["reviews"]:
        if child["key"] in keys or child["title"] in titles:
            raise OperationError("review_input_invalid", "Review keys and titles must be unique.")
        keys.add(child["key"]); titles.add(child["title"])
        fields = _review_fields(dict(provider=child["provider"], instructions=child["instructions"], review=dict(
            profile="repository_readonly_v1", repository=repository, commit=spec["commit"],
            model=child["model"], rules=child.get("rules", []))))
        manifest = json.loads(json.loads(fields["review_input_manifest"]))
        digest = json.loads(fields["review_input_digest"])
        entries.append(dict(key=child["key"], manifest=manifest, review_input_digest=digest))
        templates.append(dict(key=child["key"], title=child["title"], instructions=child["instructions"], inputs=[digest]))
    from execution_profiles import canonical, digest
    catalog = dict(version=1, reviews=entries)
    access = dict(version=1, mode="read", scopes=[repository], resources=[])
    policy = dict(version=1, max_children=len(entries), providers=sorted({c["provider"] for c in spec["reviews"]}),
                  templates=templates, max_access=access, **{k: arguments[k] for k in ("object", "scope", "effect")})
    return dict(subtask_policy=json.dumps(canonical(policy)), review_input_manifest=json.dumps(canonical(catalog)),
                review_input_digest=json.dumps(digest(catalog)))


def _do_task_create(arguments: dict) -> dict:
    import solar_state

    fields = [("title", json.dumps(arguments["title"], ensure_ascii=False)),
              ("created", json.dumps(_now_iso())),
              ("updated", json.dumps(_now_iso()))]
    review_fields = _review_fields(arguments)
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
            if raw.get("execution_profile") and not review_fields:
                raise OperationError("review_input_invalid", "A restricted revision needs fresh review inputs.")
            for key in _COPIED:
                if key in raw and raw[key].strip():
                    copied[key] = raw[key].strip()
        explicit = {key: json.dumps(arguments[key], ensure_ascii=False)
                    for key in _TEXT_FIELDS if key in arguments and key != "title"}
        merged = {**copied, **explicit}
        merged.setdefault("priority", "normal")
        if "priority" in arguments:
            merged["priority"] = arguments["priority"]
        if "access_policy" in arguments:
            merged["access_policy"] = _access_text(arguments["access_policy"])
        merged.update(review_fields)
        fields += list(merged.items())
        if source_id:
            fields.append(("revises_task_id", json.dumps(source_id)))
            fields.append(("revises_digest", json.dumps(
                solar_state.task_digest(source["status"], source["frontmatter"], source["body"]))))
        task_id = store.task_create(fields, _body(arguments["title"], arguments["instructions"]),
                                    status="draft", actor=_actor("task.create"))
        task = store.task_get(task_id)
    digest = solar_state.task_digest(task["status"], task["frontmatter"], task["body"])
    result = dict(created=True, id=task_id, status="draft", row_version=task["row_version"],
                  digest=digest, activated=False,
                  next="Review it with solar_search, then approve it with task.approve.")
    if arguments.get("queue"):
        try:
            with solar_state.session() as store:
                came = store.task_approve(task_id, actor=_actor("task.create"),
                                          expected_row_version=task["row_version"], consent="client")
                queued = store.task_get(task_id)
            digest = solar_state.task_digest(queued["status"], queued["frontmatter"], queued["body"])
            risk = solar_state.run_risk(queued["frontmatter"])
            result.update(status="queued", queued=True, row_version=queued["row_version"], digest=digest,
                          risk=risk, awaiting_approval=solar_state.needs_run_authorization(queued["frontmatter"]),
                          next=("Queued. It is confined to a verified read-only profile and runs when a place is free."
                                if risk == "low" else
                                "Queued but waiting: it is not confined, so run task.authorize_run to let it run."))
        except solar_state.StateError as exc:
            result.update(queued=False, queue_refused=str(exc)[:300])
    if source_id:
        result["revises_task_id"] = source_id
        result["source_unchanged"] = True
    return result


def _edit(task_id: str, expected: int, fields: dict, body: Optional[str], operation: str,
          definition: Optional[str] = None) -> dict:
    """Shared edit path: one transaction, never activates.

    A draft or planned task is rewritten (planned goes back to draft). A queued
    task keeps its place and its approval while the edit leaves the approved
    digest as it was, which is a rename; any other change sends it to draft and
    withdraws the approval in the same transaction, so the worker cannot claim
    the new content. An active task is never edited, and finished ones are not.
    """
    import solar_state

    with solar_state.session() as store:
        task = _task(store, task_id)
        if task["status"] == "active":
            raise OperationError(
                "task_active_immutable",
                "An active task keeps the instructions it started with. Request cancellation, "
                "wait for it to stop, then revise it with task.create and revises_task_id.")
        if task["status"] not in ("draft", "planned", "queued"):
            raise OperationError(
                "task_not_editable",
                f"{task_id} is {task['status']}. Finished tasks keep what was "
                "approved; prepare a revision with task.create and revises_task_id.")
        fields = dict(fields, updated=json.dumps(_now_iso()))
        # A planned task was reviewed as it stood: any change sends it back to draft.
        result = store.task_update(
            task_id, expected_row_version=expected,
            allowed_status=("draft", "planned", "queued"), fields=fields, body=body,
            definition=definition, to_status="draft" if task["status"] == "planned" else None,
            actor=_actor(operation))
    result.update(activated=False, needs_approval=result["status"] != "queued")
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
    current_fields = dict(current["frontmatter"])
    if ((current_fields.get("execution_profile") and "review_batch" in changes)
            or (current_fields.get("subtask_policy") and "review" in changes)):
        raise OperationError("review_input_invalid", "Changing between a review and a parent batch needs a new revision.")
    if (dict(current["frontmatter"]).get("execution_profile")
            and set(changes) & {"instructions", "provider", "access_policy"} and "review" not in changes):
        raise OperationError("review_input_invalid", "Restricted edits require fresh review inputs.")
    fields = {key: _fm(value) for key, value in changes.items() if key in _TEXT_FIELDS}
    fields.update(_review_fields(arguments))
    if "priority" in changes:
        fields["priority"] = changes["priority"]
    if "access_policy" in changes:
        fields["access_policy"] = _access_text(changes["access_policy"])
    body = None
    definition = None
    title = changes.get("title", old_title)
    if "instructions" in changes:
        # Replaces the instructions only: what earlier runs appended stays in the body.
        definition = _body(title, changes["instructions"])
    elif "title" in changes:
        heading = f"\n# {old_title}\n"
        if current["body"].startswith(heading):
            body = f"\n# {title}\n" + current["body"][len(heading):]
    return _edit(arguments["task_id"], arguments["expected_row_version"], fields, body,
                 "task.update", definition=definition)


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
                                  expected_row_version=arguments["expected_row_version"], consent="client")
        task = store.task_get(task_id)
    stored = {key: solar_state.value_of(rest) for key, rest in task["frontmatter"]}
    risk = solar_state.run_risk(task["frontmatter"])
    waiting = solar_state.needs_run_authorization(task["frontmatter"])
    return dict(approved=True, id=task_id, from_status=came, to_status="queued",
                approved_digest=stored.get("approved_digest"), row_version=task["row_version"],
                risk=risk, awaiting_approval=waiting,
                next=("Waiting: it is not confined to a verified read-only profile; run task.authorize_run "
                      "to let it run." if waiting else "Queued; it runs when a place is free."))


def _do_async_propose(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        applied = store.async_policy()
        document = dict(
            schema_version=solar_state.POLICY_SCHEMA_VERSION, revision=applied["revision"] + 1,
            global_capacity=arguments["global_capacity"],
            provider_capacity=({item["provider"]: item["limit"] for item in arguments["provider_limits"]}
                               if "provider_limits" in arguments else applied["provider_capacity"]),
            exclusive_wait_seconds=arguments.get("exclusive_wait_seconds",
                                                 applied["exclusive_wait_seconds"]),
            enabled_reader_profiles=sorted(arguments.get("enabled_reader_profiles",
                                                         applied["enabled_reader_profiles"])))
        normalized = solar_state.validate_policy_document(document, applied["revision"])
        path = solar_state.write_proposal(normalized, store.root)
    return dict(proposed=True, revision=normalized["revision"], path=str(path),
                proposal_digest=solar_state.policy_digest(normalized), applied=False,
                next="Apply it with async_execution.apply using this revision and digest.")


def _do_async_apply(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        proposal = solar_state.read_proposal(store.root)
        if not proposal["present"]:
            raise OperationError("proposal_missing", "There is no proposal file; prepare one with "
                                 "async_execution.propose.")
        document = proposal["document"]
        if (not isinstance(document, dict) or document.get("revision") != arguments["revision"]):
            raise OperationError("proposal_changed", "The proposal file is not the revision that was approved.")
        try:
            applied = store.async_policy_apply(document, actor=_actor("async_execution.apply"),
                                               expected_digest=arguments["proposal_digest"])
        except solar_state.ProposalChanged as exc:
            raise OperationError("proposal_changed", str(exc)) from None
        except solar_state.PolicyInvalid as exc:
            raise OperationError("policy_invalid", str(exc)) from None
    return dict(applied=True, revision=applied["revision"], global_capacity=applied["global_capacity"],
                provider_capacity=applied["provider_capacity"],
                exclusive_wait_seconds=applied["exclusive_wait_seconds"],
                enabled_reader_profiles=applied["enabled_reader_profiles"])


def _do_task_authorize_run(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        return store.task_authorize_run(arguments["task_id"],
                                        expected_row_version=arguments["expected_row_version"],
                                        actor=_actor("task.authorize_run"))


def _do_task_return_to_draft(arguments: dict) -> dict:
    import solar_state

    with solar_state.session() as store:
        result = store.task_return_to_draft(
            arguments["task_id"], expected_row_version=arguments["expected_row_version"],
            actor=_actor("task.return_to_draft"))
    return dict(result, returned=True, queued=False, activated=False, needs_approval=True)


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


def _do_task_wait(arguments: dict) -> dict:
    """One read-only call that waits for a terminal status, up to `timeout_seconds`.

    Sleeps in short slices and re-reads the row each slice; one read session per
    slice so a concurrent writer (worker, transition) is never held blocked by a
    sleeping reader. The deadline rules every step, including taking the lock:
    the lock is asked for in short steps, the transport is served between
    attempts, and both the row read and the result-view read get only the
    caller's remaining budget — a blocked state never stretches the wait past
    the cap nor raises out of it. Nothing here mutates: the gate sees an A0 read.
    """
    import time

    import solar_state
    import task_views
    import transport_pulse

    task_id = arguments["task_id"]
    timeout = arguments.get("timeout_seconds") or 60
    poll = max(0.25, min(arguments.get("poll_seconds") or 1.0,
                         timeout / 2 if timeout > 1 else 1.0))
    started = time.monotonic()
    deadline = started + timeout
    # One bounded attempt at the lock. A blocked state is retried after a short
    # transport pulse, so a ping sent while the state is busy is answered in a
    # fraction of a second, not after the whole remaining budget.
    lock_step = 0.1

    def elapsed() -> int:
        return round(time.monotonic() - started)

    def budget() -> float:
        return max(0.05, deadline - time.monotonic())

    def cancelled_result() -> dict:
        return dict(id=task_id, status=_last_status, row_version=last_version,
                    waited=False, elapsed_seconds=elapsed(), cancelled_by_client=True,
                    next="The caller cancelled the request; the task is untouched. "
                         "Call task.wait again to keep waiting.")

    def timeout_result(next_text: str) -> dict:
        return dict(id=task_id, status=_last_status, row_version=last_version,
                    waited=False, elapsed_seconds=elapsed(), timeout_seconds=timeout,
                    next=next_text)

    def yield_to_transport() -> bool:
        """A short pause between lock attempts; False means the caller cancelled."""
        return transport_pulse.wait(min(0.05, max(0.01, deadline - time.monotonic())))

    _last_status, last_version = "unknown", None
    while True:
        if time.monotonic() >= deadline:
            return timeout_result("Still %s. Call task.wait again to keep waiting." % _last_status)
        # The row read: the lock is asked for in short steps until it is granted
        # or the budget runs out; between attempts the drain answers.
        task = None
        while task is None and time.monotonic() < deadline:
            try:
                with solar_state.read_session(timeout=min(lock_step, budget())) as store:
                    task = _task(store, task_id)
            except solar_state.StateBusy:
                if not yield_to_transport():
                    return cancelled_result()
        if task is None:                     # the budget was spent under a busy state
            return timeout_result("The state lock stayed busy; call task.wait again "
                                  "to keep waiting.")
        _last_status, last_version = task["status"], task["row_version"]
        if task["status"] in solar_state.TERMINAL_STATUSES:
            shown = None
            while shown is None and time.monotonic() < deadline:
                try:
                    shown = task_views.view_task(task_id, "result",
                                                 lock_timeout=min(lock_step, budget()))
                except solar_state.StateBusy:
                    if not yield_to_transport():
                        return cancelled_result()
            if shown is None:                # terminal row seen, its view unreachable in budget
                return timeout_result(
                    "The task already finished (%s); only its result view could not be "
                    "read inside this budget. Call task.wait again, or read the result "
                    "now with solar_search scope=tasks task_id=%s view=result."
                    % (_last_status, task_id))
            return dict(id=task_id, status=task["status"], row_version=task["row_version"],
                        waited=True, elapsed_seconds=elapsed(),
                        result=dict(results=shown.get("results", []),
                                    execution_log=shown.get("execution_log"),
                                    recorded=shown.get("recorded", False)))
        if task["status"] == "queued" and solar_state.needs_run_authorization(task["frontmatter"]):
            return dict(id=task_id, status="queued", row_version=task["row_version"],
                        waited=False, elapsed_seconds=elapsed(), awaiting_approval=True,
                        next="The task waits for task.authorize_run; waiting longer cannot finish it. "
                             "Authorize the run (native confirmation) and call task.wait again.")
        slice_seconds = max(0.0, min(poll, deadline - time.monotonic()))
        if slice_seconds <= 0.0:
            continue
        if not transport_pulse.wait(slice_seconds):
            return cancelled_result()


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
_SCOPE = {"type": "string", "minLength": 1, "maxLength": 1000, "pattern": r"/[^\x00-\x1f\x7f]*",
          "description": "Absolute path."}
_ACCESS = _obj(dict(
    mode={"type": "string", "enum": ["read", "write"]},
    scopes={"type": "array", "items": _SCOPE, "maxItems": 32, "uniqueItems": True,
            "description": "Files or folders the task touches. A writer needs at least one."},
    resources={"type": "array", "items": SLUG, "maxItems": 32, "uniqueItems": True,
               "description": "Resources held exclusively while it runs, e.g. a browser session."}),
    required=("mode",))
_REVIEW = _obj(dict(
    profile={"type": "string", "enum": ["text_only_review_v1", "repository_readonly_v1"]},
    model=LINE(160), rules={"type": "array", "items": LINE(1000), "maxItems": 32},
    repository={"type": "string", "pattern": r"/[^\x00-\x1f\x7f]*", "maxLength": 1000},
    commit={"type": "string", "pattern": r"[0-9a-f]{40}|[0-9a-f]{64}"},
    evidence={"type": "array", "maxItems": 128, "items": _obj(dict(
        source_path={"type": "string", "pattern": r"/[^\x00-\x1f\x7f]*", "maxLength": 1000},
        content={"type": "string", "maxLength": 98304},
        sha256={"type": "string", "pattern": r"[0-9a-f]{64}"}), required=("source_path", "content", "sha256"))}),
    required=("profile", "model"))

_REVIEW_BATCH = _obj(dict(repository=_REVIEW["properties"]["repository"],
    commit=_REVIEW["properties"]["commit"], reviews={"type": "array", "minItems": 1, "maxItems": 5,
        "items": _obj(dict(key=SLUG, title=_TITLE, instructions=_INSTRUCTIONS,
                           provider={"type": "string", "enum": ["claude", "codex", "agent", "agy"]}, model=LINE(160),
                           rules=_REVIEW["properties"]["rules"]),
                      required=("key", "title", "instructions", "provider", "model"))}),
    required=("repository", "commit", "reviews"))

_CAPACITY = {"type": "integer", "minimum": 1, "maximum": 5}

OPERATIONS: dict[str, Operation] = {op.name: op for op in (
    Operation(
        "task.create", A2, "Create a draft task (or a draft revision), and queue it when queue is true.",
        _obj(dict(title=_TITLE, instructions=_INSTRUCTIONS, object=LINE(500), scope=LINE(500),
                  effect=LINE(500), priority=_PRIORITY, provider=SLUG, planet=SLUG, agent=SLUG,
                  responsibility=SLUG, revises_task_id=TASK_ID, access_policy=_ACCESS, review=_REVIEW, review_batch=_REVIEW_BATCH,
                  queue={"type": "boolean", "description": "Queue it right away, as task.approve would. For work "
                         "that should run now; a risky task still waits for task.authorize_run."}),
             required=("title", "instructions")),
        errors=("task_not_found", "revision_unsupported", "access_policy_invalid", "review_input_invalid"),
        client_consent=True,
        effects="Writes one draft row. " + _APPROVED_ONLY + " revises_task_id copies "
                "configuration, schedule and access declaration from that task and leaves it untouched. "
                "access_policy declares what the task reads or writes; a task that declares nothing runs alone."),
    Operation(
        "task.update", A2, "Edit the content of a draft, planned or queued task.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION, title=_TITLE,
                  instructions=_INSTRUCTIONS, object=LINE(500), scope=LINE(500), effect=LINE(500),
                  priority=_PRIORITY, provider=SLUG, planet=SLUG, agent=SLUG,
                  responsibility=SLUG, access_policy=_ACCESS, review=_REVIEW, review_batch=_REVIEW_BATCH),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_active_immutable", "task_not_editable", "review_input_invalid",
                "no_changes", "access_policy_invalid"),
        client_consent=True,
        effects="Rewrites the draft. A planned task returns to draft. A queued task that is only "
                "renamed keeps its place and its approval; any other change returns it to draft and "
                "withdraws the approval. Results, delivery and errors of earlier runs are kept. "
                + _APPROVED_ONLY),
    Operation(
        "task.schedule", A2, "Set the schedule and recurrence of a draft, planned or queued task.",
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
        client_consent=True,
        effects="Stores the schedule. A queued task returns to draft and loses its approval; run "
                "counters and the last run time are kept. " + _APPROVED_ONLY),
    Operation(
        "task.approve", A2, "Move a draft or planned task to the queue.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        refuses_mandate=True,
        client_consent=True,
        effects="Queues the task as it is stored now; a later edit invalidates this approval. A task the "
                "executor does not confine to a verified read-only profile then waits (awaiting_approval) for "
                "task.authorize_run. "
                "Refuses a revision while the task it replaces can still run."),
    Operation(
        "task.authorize_run", A2, "Authorize a queued high-risk task to run, as stored now.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        refuses_mandate=True,
        effects="A task queued without a form whose execution is not confined by a verified restricted "
                "profile waits (awaiting_approval) until this runs. Bound to the approved content: an edit "
                "withdraws it. Read-only reviews with a verified profile never need it."),
    Operation(
        "task.return_to_draft", A2, "Withdraw a queued task back to draft, keeping its id and history.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        client_consent=True,
        effects="Only a queued task. Its approval is withdrawn (the previous digest stays in the "
                "audit), the worker can no longer claim it and it needs task.approve to be queued "
                "again. Body, schedule, run counters and history are kept. " + _APPROVED_ONLY),
    Operation(
        "task.cancel", A2, "Cancel a queued task, or request cancellation of an active one.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        client_consent=True,
        effects="A queued task becomes cancelled; an active one stays active until the worker stops."),
    Operation(
        "task.requeue", A2, "Move a task from error back to the queue.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION),
             required=("task_id", "expected_row_version")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        client_consent=True,
        effects="Drops the recorded execution error; instructions are unchanged."),
    Operation(
        "task.wait", A0, "Wait for one task to reach a terminal status and return its result view.",
        _obj(dict(task_id=TASK_ID,
                  timeout_seconds={"type": "integer", "minimum": 1, "maximum": 90,
                                   "description": "Cap per call, below the client request "
                                   "timeouts; a still-running task returns its status and "
                                   "next, never an error. Default 60."},
                  poll_seconds={"type": "integer", "minimum": 1, "maximum": 30,
                                "description": "Slice between reads; defaults to 1 s."}),
             required=("task_id",)),
        errors=("task_not_found", "invalid_arguments"),
        effects="Read-only wait: no claim, no transition, no write. It waits inside one call up to "
                "timeout_seconds and answers with the final status and the task's result view; the "
                "result view is evidence of the run, not new authority."),
    Operation(
        "task.archive", A2, "Archive a task, keeping its row, events and body.",
        _obj(dict(task_id=TASK_ID, expected_row_version=ROW_VERSION, reason=LINE(300)),
             required=("task_id", "expected_row_version", "reason")),
        errors=("task_not_found", "task_changed", "task_state_refused"),
        client_consent=True,
        effects="A queued task, a recurrence waiting for its next run included, is cancelled and "
                "archived in one step. Refused while the task is active, while another task waits "
                "on it, or while its subtasks run."),
    Operation(
        "async_execution.propose", A2,
        "Prepare the next revision of the async execution configuration (capacity and limits) as a readable file.",
        _obj(dict(global_capacity=_CAPACITY,
                  provider_limits={"type": "array", "maxItems": 16, "items": _obj(
                      dict(provider=SLUG, limit=_CAPACITY), required=("provider", "limit"))},
                  exclusive_wait_seconds={"type": "integer", "minimum": 1, "maximum": 86400},
                  enabled_reader_profiles={"type": "array", "items": SLUG, "maxItems": 16,
                                           "uniqueItems": True}),
             required=("global_capacity",)),
        errors=("policy_invalid", "state_unavailable"),
        effects="Writes <runtime>/async-tasks/config/async-execution.json with the next revision. "
                "The file is only a proposal: nothing changes until async_execution.apply applies it. "
                "Fields not named keep the applied values."),
    Operation(
        "async_execution.apply", A2,
        "Apply a prepared revision of the async execution configuration to the runtime.",
        _obj(dict(revision={"type": "integer", "minimum": 1, "maximum": 1_000_000},
                  proposal_digest={"type": "string", "minLength": 64, "maxLength": 64,
                                   "pattern": r"[0-9a-f]{64}"}),
             required=("revision", "proposal_digest")),
        errors=("proposal_missing", "proposal_changed", "policy_invalid", "state_unavailable"),
        effects="Replaces the applied policy in one transaction if the file still holds exactly the "
                "approved revision and digest and validates; otherwise the applied policy stays. Every "
                "claim reads the applied revision. Lowering the capacity never stops a running task."),
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
    "task.authorize_run": _do_task_authorize_run,
    "task.return_to_draft": _do_task_return_to_draft,
    "task.cancel": _do_task_cancel,
    "task.requeue": _do_task_requeue,
    "task.wait": _do_task_wait,
    "task.archive": _do_task_archive,
    "async_execution.propose": _do_async_propose,
    "async_execution.apply": _do_async_apply,
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
    if isinstance(exc, solar_state.PolicyInvalid):
        return "policy_invalid"
    if isinstance(exc, solar_state.TransitionRefused):
        return "task_state_refused"
    if isinstance(exc, solar_state.StateUnavailable):
        return "state_unavailable"
    if isinstance(exc, solar_state.StateError):
        return "state_refused"
    return "operation_failed"
