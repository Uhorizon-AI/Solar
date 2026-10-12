"""The words of a confirmation: compact, human, derived from validated state, never binding."""
import json
import queue
from pathlib import Path
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
    lines = [row.strip() for row in message.splitlines()]
    assert "− line two" in lines and "+ line 2" in lines
    assert "line one" not in lines and "line three" not in lines   # unchanged lines are not repeated
    assert "stored draft is rewritten" in message and "Nothing is queued" in message
    assert_clean(message, made)
    same = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], title="Old title"))
    assert "no difference from the stored task" in same


def test_many_changed_lines_keep_both_removals_and_additions(solar_env):
    old = "\n".join(f"old {i}" for i in range(8))
    new = "\n".join(f"new {i}" for i in range(8))
    made = new_task("Big edit", old)
    message = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], instructions=new))
    rows = [row.strip() for row in message.splitlines()]
    assert any(row.startswith("− old") for row in rows) and any(row.startswith("+ new") for row in rows)
    assert "16 lines changed" in message
    one_sided = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                         instructions=old + "\n" + "\n".join(f"add {i}" for i in range(6))))
    assert sum(row.strip().startswith("+ add") for row in one_sided.splitlines()) == 4


def test_whitespace_only_change_is_not_reported_as_no_change(solar_env):
    made = new_task("A  B")
    message = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], title="A B"))
    assert "title: A  B → A B" in message and "no difference" not in message
    body = new_task("Spacing", "keep\nthis  now")
    interior = text("task.update", dict(task_id=body["id"], expected_row_version=body["row_version"],
                                        instructions="keep\nthis now"))
    rows = [row.strip() for row in interior.splitlines()]
    assert "− this  now" in rows and "+ this now" in rows
    # Trailing blanks are trimmed by the store (task.update writes instructions.rstrip()),
    # so adding one is genuinely no change.
    trailing = text("task.update", dict(task_id=body["id"], expected_row_version=body["row_version"],
                                        instructions="keep\nthis  now \n"))
    assert "Changes: no difference from the stored task" in trailing


def test_long_changed_line_shows_its_difference_on_both_sides(solar_env):
    prefix = "x" * 300
    made = new_task("Long line", f"{prefix}-old tail\nsecond")
    message = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                       instructions=f"{prefix}-new tail\nsecond"))
    rows = [row.strip() for row in message.splitlines()]
    minus = next(row for row in rows if row.startswith("− "))
    plus = next(row for row in rows if row.startswith("+ "))
    assert "-old" in minus and "-new" in plus and minus[2:] != plus[2:]
    assert max(len(row) for row in rows) < 260


def test_long_values_are_cut_where_they_differ(solar_env):
    made = new_task("A" * 190 + "-old")
    message = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                       title="A" * 190 + "-new"))
    row = next(r for r in message.splitlines() if r.strip().startswith("title:"))
    before, after = row.split(": ", 1)[1].split(" → ")
    assert before != after and before.endswith("-old") and after.endswith("-new")


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
    message = text("telegram.send", dict(text="pay \u202eevil\u200b\x07", chat_id="42"))
    assert "\u202e" not in message and "\u200b" not in message and "\x07" not in message
    assert "\\u202e" in message and "\\u200b" in message and "\\x07" in message
    title = text("task.archive", dict(task_id="x", expected_row_version=1, reason="a\u202eb\nc"))
    assert "\u202e" not in title and "\n" not in title.split("Reason: ")[1].split("\n")[0]


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


# ---- review follow-ups ------------------------------------------------------------------------

def test_invisible_class_is_written_with_explicit_escapes():
    """The hiding characters must stay spelled out in the source, never pasted in raw."""
    line = next(row for row in Path(approval_text.__file__).read_text(encoding="utf-8").splitlines()
                if row.startswith("_INVISIBLE"))
    assert line.isascii(), "raw hidden characters pasted into the source"
    for escape in ("\\u200b-\\u200f", "\\u202a-\\u202e", "\\u2066-\\u2069", "\\ufeff"):
        assert escape in line, escape
    for code in [0x00, 0x07, 0x7f, 0x9f, 0x200b, 0x200f, 0x202a, 0x202e, 0x2066, 0x2069, 0xfeff]:
        assert approval_text._INVISIBLE.fullmatch(chr(code)), hex(code)
    for plain in ["a", " ", "\n", "é", "→", "…"]:
        assert not approval_text._INVISIBLE.fullmatch(plain)


def test_approve_shows_recurrence_limits_and_distinguishes_them(solar_env):
    def approve_text(**schedule):
        made = new_task("Weekly", "Do it.")
        run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                  scheduled_time="09:00", scheduled_timezone="UTC", scheduled_weekdays=[1],
                                  recurring=True, **schedule))
        row = stored(made["id"])
        return text("task.approve", dict(task_id=made["id"], expected_row_version=row["row_version"]))
    once = approve_text(recurring_max_runs=1)
    unlimited = approve_text()
    capped = approve_text(recurring_max_runs=1, recurring_min_interval=86400)
    assert "at most 1 runs" in once and "unlimited" in unlimited and once != unlimited
    assert "Repeats: yes" in once and "minimum gap 24.0 h" in capped


def test_requeue_shows_what_would_run_again(solar_env):
    import solar_state

    def errored(scope, effect):
        made = new_task("Same title", "Same instructions.", scope=scope, effect=effect, object="Report")
        run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
        with solar_state.session() as store:
            store.task_transition(made["id"], "active", expected_from="queued", actor="t", claimed_by="w", claimed_at="2026-01-01T00:00:00Z")
            store.task_transition(made["id"], "error", expected_from="active", actor="t")
        return made, text("task.requeue", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    first_task, first = errored("Read the finance folder", "Writes one report.")
    _, second = errored("Delete old backups", "Removes files.")
    assert first != second
    assert "Scope: Read the finance folder" in first and "Declared effect: Writes one report." in first
    assert "Scope: Delete old backups" in second and "Declared effect: Removes files." in second
    assert "Object: Report" in first and "Instructions: Same instructions." in first
    assert "runs again with the same instructions" in first
    assert_clean(first, first_task)


@pytest.mark.parametrize("operation", ["task.archive", "task.update", "task.schedule", "task.approve",
                                       "task.cancel", "task.requeue"])
def test_unreadable_task_is_flagged_without_raising(solar_env, monkeypatch, operation):
    monkeypatch.setattr(approval_text, "_facts", lambda task_id: None)
    args = dict(task_id="t", expected_row_version=1, reason="r")
    if operation == "task.update":
        args["title"] = "x"
    if operation == "task.schedule":
        args["scheduled_time"] = "09:00"
    message = text(operation, {k: v for k, v in args.items() if operation == "task.archive" or k != "reason"})
    assert "Warning: The task could not be read" in message
    assert not message.startswith("Approve action")   # the specific renderer answered, no exception


def test_fallback_for_task_operations_hides_identifiers(solar_env, monkeypatch):
    monkeypatch.setitem(approval_text.RENDERERS, "task.update", lambda *a: 1 / 0)
    message = text("task.update", dict(task_id="secret-id-123", expected_row_version=7, title="New"))
    assert message.startswith("Approve action\nOperation: task.update\ntitle: New")
    assert "secret-id-123" not in message and "7" not in message.split("\n\n")[0]


def test_language_table_is_loaded_once(solar_env):
    approval_text.language()
    first = approval_text._tokens()
    approval_text.language()
    assert approval_text._tokens() is first


def test_excerpt_escapes_hidden_characters_and_reports_original_length(solar_env):
    made = new_task("Tricky", "safe \u202e hidden " + "y" * 600)
    message = text("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert "\u202e" not in message and "\\u202e" in message and "characters in total" in message


def test_excerpt_width_is_bounded_after_escaping(solar_env):
    for payload in ("\u202e", "\u200b", "\x07"):
        made = new_task("Wide", payload * 500)
        message = text("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
        row = next(r for r in message.splitlines() if r.startswith("Instructions:"))
        assert len(row) < 450 and "characters in total" in row
        assert not row.split("…")[0].endswith(("\\", "\\u", "\\x"))
        assert payload not in message


def test_diff_pairs_lines_inside_their_block_not_across_an_insertion(solar_env):
    long = "A" * 200
    made = new_task("Insertion", f"header\n{long}-OLD\nfooter")
    message = text("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                       instructions=f"header\nextra line\n{long}-NEW\nfooter"))
    rows = [row.strip() for row in message.splitlines()]
    minus = next(row for row in rows if row.startswith("− "))
    plus = [row for row in rows if row.startswith("+ ")]
    assert "-OLD" in minus
    assert "+ extra line" in plus and any("-NEW" in row for row in plus)


def test_every_copy_key_exists_in_both_languages_and_is_used():
    # A textual scan: a key built dynamically (copy[f"..."]) would be reported as unused.
    # Select between literal keys instead, e.g. copy["a" if cond else "b"].
    assert set(approval_text.COPY["en"]) == set(approval_text.COPY["es"])
    source = Path(approval_text.__file__).read_text(encoding="utf-8")
    code = source[:source.index("COPY = {")] + source[source.index("def language"):]
    unused = [key for key in approval_text.COPY["en"] if f'"{key}"' not in code and f"'{key}'" not in code]
    assert not unused, unused


def test_diff_cost_does_not_depend_on_repetitive_lines(solar_env):
    import time
    made = new_task("Repeats", "a\n" * 10000 + "old")
    args = dict(task_id=made["id"], expected_row_version=made["row_version"], instructions="a\n" * 10000 + "new")
    started = time.monotonic()
    message = text("task.update", args)
    assert time.monotonic() - started < 1.0
    rows = [row.strip() for row in message.splitlines()]
    assert "− old" in rows and "+ new" in rows


def test_diff_cost_is_bounded_when_everything_differs(solar_env):
    import time
    old = "\n".join("x" * (i % 7) + "a" for i in range(3000))
    new = "\n".join("y" * (i % 5) + "b" for i in range(3000))
    started = time.monotonic()
    message = approval_text._diff_lines(approval_text.COPY["en"], old, new)
    assert time.monotonic() - started < 1.0
    assert any(row.startswith("− ") for row in message) and any(row.startswith("+ ") for row in message)
    assert message[-1].startswith("… 6000 lines changed")


def test_large_block_still_pairs_the_edited_line_after_inserted_lines(solar_env):
    long = "A" * 200
    old = "\n".join([f"{long}-OLD"] + [f"o{i}" for i in range(150)])
    new = "\n".join([f"ins{i}" for i in range(14)] + [f"{long}-NEW"] + [f"n{i}" for i in range(150)])
    assert len(old.split("\n")) * len(new.split("\n")) > approval_text._DIFF_BUDGET
    rows = approval_text._diff_lines(approval_text.COPY["en"], old, new)
    assert any(row.startswith("− ") and "-OLD" in row for row in rows)
    assert any(row.startswith("+ ") and "-NEW" in row for row in rows)
