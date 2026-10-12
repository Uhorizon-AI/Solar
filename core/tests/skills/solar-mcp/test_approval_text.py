"""The words of a confirmation: compact, human, derived from validated state, never binding."""
import json
import queue
from io import StringIO

import pytest

import approval_text
import mcp_approve
import mcp_server
import operations
from mcp_helpers import new_task, run, stored


def text(operation, arguments, lang="en"):
    return approval_text.render(operation, arguments, seconds=120, lang=lang)[0]


def archive_args(made, reason="Obsolete review."):
    return dict(task_id=made["id"], expected_row_version=made["row_version"], reason=reason)


def archive_grants():
    """Approvals minted for the call under test (new_task itself grants task.create)."""
    return [row for row in mcp_approve.listing() if row["tool"] != "task.create"]


def assert_clean(message, made=None):
    """No JSON, identifiers, hashes, row versions or empty fields."""
    assert "{" not in message and '"' not in message
    assert "None" not in message and "null" not in message and "[]" not in message
    if made:
        assert made["id"] not in message and made["digest"] not in message
        assert "row_version" not in message and "digest" not in message
    for row in message.splitlines():
        assert not row.endswith(": "), row


def test_archive_text_matches_the_example(solar_env):
    made = new_task("Review solar-context-sustainability plan: Gemini")
    message = text("task.archive", archive_args(made, "stale review."))
    assert message.splitlines()[:4] == [
        "Archive task",
        "Task: Review solar-context-sustainability plan: Gemini",
        "Reason: stale review.",
        "Effect: the task is archived and keeps its history.",
    ]
    assert_clean(message, made)
    assert len(message.splitlines()) <= 7


def test_archive_text_in_spanish_and_default_english(solar_env):
    made = new_task("Plan")
    assert text("task.archive", archive_args(made), "es").startswith("Archivar tarea\nTarea: Plan\nMotivo:")
    assert approval_text.language() == "en"
    (solar_env.workspace / ".solar" / "settings.json").write_text('{"language": "es-ES"}', encoding="utf-8")
    assert approval_text.language() == "es"
    (solar_env.workspace / ".solar" / "settings.json").write_text('{"language": "klingon"}', encoding="utf-8")
    assert approval_text.language() == "en"


def test_archive_effect_reflects_the_implemented_behaviour(solar_env):
    import solar_state
    made = new_task("Weekly", "x")
    run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                              scheduled_time="09:00", scheduled_timezone="Europe/Madrid",
                              scheduled_weekdays=[1], recurring=True))
    row = stored(made["id"])["row_version"]
    run("task.approve", dict(task_id=made["id"], expected_row_version=row))
    queued = stored(made["id"])
    message = text("task.archive", dict(task_id=made["id"], expected_row_version=queued["row_version"], reason="r"))
    assert "recurrence is stopped" in message and "history is kept" in message
    with solar_state.session() as store:
        store.task_transition(made["id"], "active", expected_from="queued", actor="t", claimed_by="w", claimed_at="2026-01-01T00:00:00Z")
    active = stored(made["id"])
    assert "refused while the task is running" in text(
        "task.archive", dict(task_id=made["id"], expected_row_version=active["row_version"], reason="r"))


def test_stale_and_missing_tasks_are_flagged_not_hidden(solar_env):
    made = new_task("Plan")
    stale = dict(archive_args(made), expected_row_version=made["row_version"] + 5)
    assert "changed after it was read" in text("task.archive", stale)
    gone = dict(archive_args(made), task_id="does-not-exist")
    assert "task was not found" in text("task.archive", gone)


def test_update_shows_before_and_after_only_for_changes(solar_env):
    made = new_task("Old title", "line one\nline two\nline three")
    message = text("task.update", dict(
        task_id=made["id"], expected_row_version=made["row_version"], title="New title",
        priority="normal", instructions="line one\nline 2\nline three"))
    assert "title: Old title → New title" in message
    assert "priority" not in message                      # unchanged: not listed
    assert "− line two" in message and "+ line 2" in message
    assert "line one" not in message.replace("line one\n", "")  # unchanged lines are not repeated
    assert "stored draft is rewritten" in message and "Nothing is queued" in message
    assert_clean(message, made)
    same = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], title="Old title"))
    assert "no difference from the stored task" in same


def test_update_of_a_planned_task_says_it_returns_to_draft(solar_env):
    made = new_task("Plan")
    run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                              scheduled_time="08:30", scheduled_timezone="UTC"))
    current = stored(made["id"])
    assert current["status"] == "planned" or current["status"] == "draft"
    message = text("task.update", dict(task_id=made["id"], expected_row_version=current["row_version"], effect="Writes a file."))
    assert ("returns to draft" in message) == (current["status"] == "planned")


def test_schedule_shows_days_time_zone_and_recurrence_limits(solar_env):
    made = new_task("Weekly report")
    message = text("task.schedule", dict(
        task_id=made["id"], expected_row_version=made["row_version"], scheduled_time="09:15",
        scheduled_timezone="Europe/Madrid", scheduled_weekdays=[1, 3], recurring=True,
        recurring_max_runs=5, recurring_min_interval=86400))
    assert "Days: Mon, Wed" in message and "Time: 09:15" in message and "Time zone: Europe/Madrid" in message
    assert "Repeats: yes (minimum gap 24.0 h; at most 5 runs)" in message
    assert "Next runs:" in message and "not queued" in message
    assert_clean(message, made)
    spanish = text("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                         scheduled_time="09:15", scheduled_timezone="Europe/Madrid",
                                         scheduled_weekdays=[1, 3]), "es")
    assert "Días: lun, mié" in spanish and "Zona horaria: Europe/Madrid" in spanish
    assert "Repite: no" in spanish


def test_invalid_schedule_is_reported_the_way_the_handler_refuses_it(solar_env):
    made = new_task("Weekly report")
    message = text("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                         scheduled_time="09:00", scheduled_timezone="Mars/Olympus"))
    assert "Warning: unknown time zone" in message


def test_approve_explains_that_it_authorizes_execution(solar_env):
    made = new_task("Quarterly review", "Open the report and summarize it.", effect="Writes one local report.")
    message = text("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert message.startswith("Approve task for execution\nTask: Quarterly review")
    assert "authorizes the task to run" in message and "a worker will execute" in message
    assert "Declared effect: Writes one local report." in message
    assert "Instructions: Open the report and summarize it." in message
    assert_clean(message, made)


def test_long_instructions_are_excerpted_with_the_total_length(solar_env):
    made = new_task("Long", "word " * 400)
    message = text("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert "1999 characters in total" in message and len(message) < 1400


def test_cancel_distinguishes_immediate_cancellation_from_a_stop_request(solar_env):
    import solar_state
    made = new_task("Job")
    run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    queued = stored(made["id"])
    args = dict(task_id=made["id"], expected_row_version=queued["row_version"])
    now = text("task.cancel", args)
    assert now.startswith("Cancel task") and "cancelled immediately and will not run" in now
    with solar_state.session() as store:
        store.task_transition(made["id"], "active", expected_from="queued", actor="t", claimed_by="w", claimed_at="2026-01-01T00:00:00Z")
    request = text("task.cancel", dict(args, expected_row_version=stored(made["id"])["row_version"]))
    assert request.startswith("Request task stop") and "stays active until its worker stops it" in request
    assert "immediately" not in request


def test_requeue_and_create_text(solar_env):
    made = new_task("Job")
    assert "refused: only a task in error" in text("task.requeue", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    create = text("task.create", dict(title="New one", instructions="Do it.", priority="high"))
    assert create.startswith("Create draft task\nTask: New one") and "Nothing is queued" in create
    revision = text("task.create", dict(title="New one", instructions="Do it.", revises_task_id=made["id"]))
    assert "Revises: Job" in revision and made["id"] not in revision


def test_send_shows_recipient_and_exact_untruncated_content(solar_env):
    body = "Hello\nline two with ünïcode " + "x" * 3900
    message = text("telegram.send", dict(text=body, chat_id="-1001234", parse_mode="HTML"))
    assert message.startswith("Send Telegram message\nTo: -1001234\nFormat: interpreted as HTML")
    assert "outside this machine" in message
    assert "\n".join("  " + row for row in body.split("\n")) in message
    assert "…" not in message


def test_send_makes_hidden_and_reordering_characters_visible(solar_env):
    message = text("telegram.send", dict(text="pay ‮evil​\x07", chat_id="42"))
    assert "‮" not in message and "​" not in message and "\x07" not in message
    assert "\\u202e" in message and "\\u200b" in message and "\\x07" in message
    title = text("task.archive", dict(task_id="x", expected_row_version=1, reason="a‮b\nc"))
    assert "‮" not in title and "\n" not in title.split("Reason: ")[1].split("\n")[0]


def test_summary_cannot_be_supplied_by_the_agent(solar_env):
    made = new_task("Plan")
    call = dict(operation="task.archive", arguments=dict(archive_args(made), summary="Harmless read"))
    assert mcp_server.handle(dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(
        name="solar_execute", arguments=call)), lambda *a: True)["error"]["code"] == -32602
    assert not archive_grants()


def test_every_confirmed_operation_has_a_renderer_or_a_plain_fallback(solar_env):
    for name, op in operations.OPERATIONS.items():
        if op.authority == "A2":
            assert name in approval_text.RENDERERS, name
    plain = text("action.run", dict(skill="s", action="a"))
    assert plain.startswith("Approve action") and "{" not in plain


def test_rendering_failure_falls_back_without_blocking_the_prompt(solar_env, monkeypatch):
    monkeypatch.setitem(approval_text.RENDERERS, "task.archive", lambda *a: 1 / 0)
    message = text("task.archive", dict(task_id="t", expected_row_version=3, reason="why"))
    assert message.startswith("Approve action") and "reason: why" in message


# ---- wire level: the controls are untouched -----------------------------------------------

def serve_once(call, reply, workspace_lang=None):
    lines, forms = queue.Queue(), []

    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=5)
                if line is None:
                    return
                yield line

    class Output(StringIO):
        def write(self, data):
            result = super().write(data)
            message = json.loads(data)
            if message.get("method") == "elicitation/create":
                forms.append(message["params"])
                if reply is not None:
                    lines.put(json.dumps(dict(jsonrpc="2.0", id=message["id"], result=reply)))
                    lines.put(None)
            elif message.get("id") == 2:
                lines.put(None)             # the answer is out: end the session
            return result

    lines.put(json.dumps(dict(jsonrpc="2.0", id=1, method="initialize", params=dict(capabilities={"elicitation": {}}))))
    lines.put(json.dumps(dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(name="solar_execute", arguments=call))))
    output = Output()
    mcp_server.serve(Input(), output)
    return forms, [json.loads(row) for row in output.getvalue().splitlines()][-1]


def test_archive_prompt_is_compact_single_and_still_binds_the_exact_call(solar_env):
    made = new_task("Review plan: Gemini")
    args = archive_args(made, "stale review.")
    forms, final = serve_once(dict(operation="task.archive", arguments=args), {"action": "accept", "content": {"approve": True}})
    assert len(forms) == 1
    shown = forms[0]["message"]
    assert shown.startswith("Archive task\nTask: Review plan: Gemini\nReason: stale review.")
    assert_clean(shown, made)
    assert forms[0]["requestedSchema"]["properties"]["approve"] == dict(type="boolean", title="Approve this action", default=False)
    assert final["result"]["isError"] is False
    assert stored(made["id"])["status"] == "archived"
    rows = [r for r in mcp_approve.listing() if r["tool"] == "task.archive"]
    assert len(rows) == 1 and rows[0]["consumed_at"]


@pytest.mark.parametrize("reply", [{"action": "decline"}, {"action": "cancel"},
                                   {"action": "accept", "content": {"approve": False}},
                                   {"action": "accept", "content": {}}])
def test_closing_or_rejecting_never_executes(solar_env, reply):
    made = new_task("Plan")
    forms, final = serve_once(dict(operation="task.archive", arguments=archive_args(made)), reply)
    assert len(forms) == 1 and final["result"]["isError"] is True
    assert stored(made["id"])["status"] == "draft" and not archive_grants()


def test_expiry_never_executes_and_closes_the_form(solar_env, monkeypatch):
    monkeypatch.setattr(mcp_server, "CONFIRMATION_TIMEOUT", 0.2)
    made = new_task("Plan")
    forms, final = serve_once(dict(operation="task.archive", arguments=archive_args(made)), None)
    assert len(forms) == 1 and "0.2 seconds" in forms[0]["message"]
    assert final["result"]["isError"] is True and stored(made["id"])["status"] == "draft"
    assert not archive_grants()


def test_a_stale_version_is_still_refused_after_confirmation(solar_env):
    made = new_task("Plan")
    args = archive_args(made)
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], title="Plan v2"))
    forms, final = serve_once(dict(operation="task.archive", arguments=args), {"action": "accept", "content": {"approve": True}})
    assert "changed after it was read" in forms[0]["message"]
    body = json.loads(final["result"]["content"][0]["text"])
    assert final["result"]["isError"] is True and body["code"] == "task_changed"
    assert stored(made["id"])["status"] == "draft"


def test_the_approval_binds_the_full_arguments_not_the_summary(solar_env):
    import mcp_gate
    made = new_task("Plan")
    args = archive_args(made, "reason A")
    granted = mcp_approve.grant("task.archive", args, 120, "t")
    registry = {name: op.gate_spec() for name, op in operations.OPERATIONS.items()} | {"_action_skills": {}}
    other = dict(args, reason="reason B", approval_id=granted["approval_id"])
    assert mcp_gate.preflight("task.archive", other, registry).code == "approval_scope_mismatch"
    other = dict(args, expected_row_version=args["expected_row_version"] + 1, approval_id=granted["approval_id"])
    assert mcp_gate.preflight("task.archive", other, registry).code == "approval_scope_mismatch"
