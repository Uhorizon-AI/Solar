"""The task operations of solar_execute: create, update, schedule, approve, cancel, requeue, archive."""
from __future__ import annotations

import json
import threading

import pytest

import mcp_server
import solar_state
from mcp_helpers import execute, new_task, run, search, stored
from reservation_tokens import token_of

MADRID = "Europe/Madrid"


def refuse(operation, arguments, code):
    body, error = execute(operation, arguments)
    assert error, body
    assert body.get("code") == code, body
    return body


def queued_count():
    with solar_state.session() as store:
        return len(store.task_list("queued")) + len(store.task_list("active"))


# --------------------------------------------------------------------------
# create / update never activate
# --------------------------------------------------------------------------

def test_create_stores_a_draft_and_has_no_way_to_queue(solar_env):
    made = new_task("A", "Steps.", object="o", scope="s", effect="e")
    assert made["status"] == "draft" and made["activated"] is False
    assert stored(made["id"])["status"] == "draft"
    body, error = execute("task.create", dict(title="B", instructions="x", queued=True))
    assert error and body["code"] == "invalid_arguments"
    assert queued_count() == 0


def test_update_changes_a_draft_and_bumps_the_version(solar_env):
    made = new_task("Old title", "Old body.")
    out = run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                  title="New title", instructions="New body.", effect="local only"))
    task = stored(made["id"])
    assert out["row_version"] == made["row_version"] + 1 and out["activated"] is False
    assert task["status"] == "draft" and task["title"] == "New title"
    assert "New body." in task["body"] and "Old body." not in task["body"]
    assert task["body"].startswith("\n# New title\n")
    assert out["digest"] != made["digest"]


def test_a_title_only_edit_keeps_the_instructions(solar_env):
    made = new_task("Old", "Keep these steps.")
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], title="Renamed"))
    task = stored(made["id"])
    assert task["body"].startswith("\n# Renamed\n") and "Keep these steps." in task["body"]


def test_an_empty_update_is_refused(solar_env):
    made = new_task()
    refuse("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"]), "no_changes")


def test_editing_a_planned_task_sends_it_back_to_draft_for_review(solar_env):
    made = new_task()
    with solar_state.session() as store:
        store.task_transition(made["id"], "planned", expected_from="draft")
        version = store.task_get(made["id"])["row_version"]
    out = run("task.update", dict(task_id=made["id"], expected_row_version=version, effect="changed"))
    assert out["status"] == "draft" and stored(made["id"])["status"] == "draft"
    assert queued_count() == 0


@pytest.mark.parametrize("status", ["completed", "error", "cancelled", "archived"])
def test_finished_tasks_keep_what_was_approved(solar_env, status):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"')], "\n# T\n\nOriginal.\n", status="queued")
        if status != "queued":
            store.task_claim_next("w")
            if status == "completed":
                store.task_complete(task_id, token=token_of(store, task_id))
            elif status == "error":
                store.task_fail(task_id, "\n## Execution Error\n\nboom\n", token=token_of(store, task_id))
            elif status == "cancelled":
                store.task_complete(task_id, cancelled=True, token=token_of(store, task_id))
            else:
                store.task_complete(task_id, cancelled=True, token=token_of(store, task_id))
                store.task_transition(task_id, "archived", expected_from="cancelled")
        version = store.task_get(task_id)["row_version"]
    for operation, extra in (("task.update", dict(instructions="Hijacked.")),
                             ("task.schedule", dict(scheduled_time="09:00", scheduled_timezone=MADRID))):
        body = refuse(operation, dict(task_id=task_id, expected_row_version=version, **extra),
                      "task_not_editable")
        assert "task.create" in body["error"]
    assert "Original." in stored(task_id)["body"] and "Hijacked" not in stored(task_id)["body"]


def test_the_instructions_of_an_active_task_cannot_change(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"')], "\n# T\n\nOriginal.\n", status="queued")
        store.task_claim_next("w")
        version = store.task_get(task_id)["row_version"]
    for operation, extra in (("task.update", dict(instructions="Hijacked.")),
                             ("task.schedule", dict(scheduled_time="09:00", scheduled_timezone=MADRID))):
        refuse(operation, dict(task_id=task_id, expected_row_version=version, **extra),
               "task_active_immutable")
    after = stored(task_id)
    assert after["status"] == "active" and "Hijacked" not in after["body"]
    assert after["row_version"] == version


# --------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------

@pytest.mark.parametrize("operation,extra", [
    ("task.update", dict(effect="e2")),
    ("task.schedule", dict(scheduled_time="17:00", scheduled_timezone=MADRID)),
    ("task.approve", {}),
    ("task.archive", dict(reason="r")),
])
def test_a_stale_version_is_refused_by_every_mutation(solar_env, operation, extra):
    made = new_task()
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], effect="other"))
    before = stored(made["id"])
    refuse(operation, dict(task_id=made["id"], expected_row_version=made["row_version"], **extra),
           "task_changed")
    assert stored(made["id"])["row_version"] == before["row_version"]
    assert stored(made["id"])["status"] == "draft"


def test_two_clients_editing_from_the_same_read_cannot_both_win(solar_env):
    made = new_task()
    results = []
    barrier = threading.Barrier(2)

    def writer(effect):
        barrier.wait()
        results.append(execute("task.update", dict(task_id=made["id"],
                                                   expected_row_version=made["row_version"],
                                                   effect=effect)))

    threads = [threading.Thread(target=writer, args=(e,)) for e in ("first", "second")]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    outcomes = sorted("ok" if not error else body["code"] for body, error in results)
    assert outcomes == ["ok", "task_changed"]


def test_an_approval_does_not_survive_a_later_edit(solar_env):
    """The human confirmed version N; an edit made it N+1; the confirmation is worthless."""
    import mcp_approve
    made = new_task("Plan", "Original.")
    confirmed = dict(task_id=made["id"], expected_row_version=made["row_version"])
    granted = mcp_approve.grant("task.approve", confirmed, 900, "confirmed earlier")
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                            instructions="Something the human never saw."))
    body, error = mcp_server.call_tool("solar_execute", dict(
        operation="task.approve", arguments=confirmed, approval_id=granted["approval_id"]))
    assert error and body["code"] == "task_changed"
    assert stored(made["id"])["status"] == "draft"
    assert queued_count() == 0


# --------------------------------------------------------------------------
# schedule
# --------------------------------------------------------------------------

def test_schedule_stores_time_zone_and_recurrence_without_queueing(solar_env):
    made = new_task()
    out = run("task.schedule", dict(
        task_id=made["id"], expected_row_version=made["row_version"], scheduled_time="17:00",
        scheduled_weekdays=[5], scheduled_timezone=MADRID, recurring=True))
    task = stored(made["id"])
    values = {k: solar_state.value_of(v) for k, v in task["frontmatter"]}
    assert task["status"] == "draft" and out["activated"] is False
    assert values["scheduled_time"] == "17:00" and values["scheduled_weekdays"] == "5"
    assert values["scheduled_timezone"] == MADRID and values["recurring"] == "true"
    # Weekly, less margin for a one-hour shorter week and a late finish.
    assert int(values["recurring_min_interval"]) == 7 * 86400 - 7200 == out["schedule"]["recurring_min_interval"]
    assert len(out["schedule"]["next_occurrences"]) == 4
    assert all(o["weekday"] == 5 and o["local"].split("T")[1][:5] == "17:00"
               for o in out["schedule"]["next_occurrences"])
    assert queued_count() == 0


@pytest.mark.parametrize("arguments", [
    dict(scheduled_time="17:00"),                                  # no zone: host-dependent hour
    dict(scheduled_time="17:00", scheduled_timezone="Nowhere/Land"),
    dict(scheduled_weekdays=[5], scheduled_timezone=MADRID),       # weekdays without a time
    dict(scheduled_time="17:00", scheduled_timezone=MADRID, recurring=True,
         recurring_min_interval=7 * 86400),                        # would skip after a clock change
    dict(scheduled_time="17:00", scheduled_timezone=MADRID, scheduled_weekdays=[5, 5]),
    dict(scheduled_time="25:00", scheduled_timezone=MADRID),
    dict(scheduled_time="17:00", scheduled_timezone="../../etc/passwd"),
])
def test_an_unsafe_schedule_is_refused_and_stores_nothing(solar_env, arguments):
    made = new_task()
    body, error = execute("task.schedule", dict(task_id=made["id"],
                                                expected_row_version=made["row_version"], **arguments))
    assert error and body["code"] in ("schedule_invalid", "invalid_arguments"), body
    assert stored(made["id"])["row_version"] == made["row_version"]


def test_a_daily_recurrence_gets_a_dst_safe_interval(solar_env):
    made = new_task()
    out = run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                    scheduled_time="09:00", scheduled_timezone=MADRID, recurring=True))
    assert out["schedule"]["recurring_min_interval"] == 86400 - 7200
    assert "02:00" not in " ".join(out["schedule"]["notes"])
    out = run("task.schedule", dict(task_id=made["id"], expected_row_version=out["row_version"],
                                    scheduled_time="02:30", scheduled_timezone=MADRID))
    assert any("02:00-02:59" in note for note in out["schedule"]["notes"])


# --------------------------------------------------------------------------
# approve is the only door to the queue
# --------------------------------------------------------------------------

def test_approve_queues_the_exact_stored_task_and_records_it(solar_env):
    made = new_task("Go", "Do.", object="o", scope="s", effect="e")
    out = run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    task = stored(made["id"])
    assert task["status"] == "queued" and out["approved_digest"] == made["digest"]
    # Editing what was approved sends the task back to draft: the approval is gone with it.
    out = run("task.update", dict(task_id=made["id"], expected_row_version=task["row_version"],
                                  instructions="Swapped after approval."))
    assert out["status"] == "draft" and out["needs_approval"] is True
    assert "approved_digest" not in {k for k, _ in stored(made["id"])["frontmatter"]}


def test_approve_refuses_a_task_that_is_not_a_draft(solar_env):
    made = new_task()
    run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    refuse("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]),
           "task_state_refused")


def test_nothing_but_approve_ever_queues(solar_env):
    made = new_task()
    version = made["row_version"]
    for operation, extra in (("task.update", dict(effect="e")),
                             ("task.schedule", dict(scheduled_time="17:00", scheduled_timezone=MADRID,
                                                    scheduled_weekdays=[5], recurring=True))):
        version = run(operation, dict(task_id=made["id"], expected_row_version=version, **extra))["row_version"]
    revision = run("task.create", dict(title="Rev", instructions="x", revises_task_id=made["id"]))
    assert queued_count() == 0
    with solar_state.session() as store:
        assert store.task_claim_next("worker") is None
    assert revision["status"] == "draft"


# --------------------------------------------------------------------------
# cancel / requeue / archive
# --------------------------------------------------------------------------

def test_requeue_moves_an_error_back_and_drops_the_error(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"')], "\n# T\n\nSteps.\n", status="queued")
        store.task_claim_next("w")
        store.task_fail(task_id, "\n## Execution Error\n\nboom\n", token=token_of(store, task_id))
        assert "Execution Error" in store.task_get(task_id)["body"]
    out = run("task.requeue", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"]))
    task = stored(task_id)
    assert out["to_status"] == "queued" and task["status"] == "queued"
    assert "Execution Error" not in task["body"] and "Steps." in task["body"]


def test_cancel_with_a_stale_version_is_refused(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"')], "\n# T\n", status="queued")
        version = store.task_get(task_id)["row_version"]
    refuse("task.cancel", dict(task_id=task_id, expected_row_version=version + 1), "task_changed")
    assert stored(task_id)["status"] == "queued"


def test_archive_a_recurrence_keeps_history_and_stops_it(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create(
            [("title", '"Weekly"'), ("recurring", "true"), ("scheduled_time", '"17:00"'),
             ("scheduled_timezone", f'"{MADRID}"')], "\n# Weekly\n\nSteps.\n", status="queued")
        version = store.task_get(task_id)["row_version"]
    out = run("task.archive", dict(task_id=task_id, expected_row_version=version, reason="replaced by revision"))
    assert out["archived"] and out["cancelled_first"] and out["recurring"] and out["history_preserved"]
    task = stored(task_id)
    assert task["status"] == "archived" and "Steps." in task["body"]
    history = search(scope="tasks", task_id=task_id, view="history")
    assert [e["to_status"] for e in history["events"]] == ["queued", "cancelled", "archived"]
    assert history["events"][-1]["actor"] == "mcp:task.archive"
    with solar_state.session() as store:
        assert store.task_claim_next("w") is None


def test_archive_needs_a_reason_and_refuses_an_active_task(solar_env):
    made = new_task()
    body, error = execute("task.archive", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert error and body["code"] == "invalid_arguments"
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"')], "\n# T\n", status="queued")
        store.task_claim_next("w")
        version = store.task_get(task_id)["row_version"]
    refuse("task.archive", dict(task_id=task_id, expected_row_version=version, reason="x"), "task_state_refused")
    assert stored(task_id)["status"] == "active"


# --------------------------------------------------------------------------
# revisions
# --------------------------------------------------------------------------

def test_a_revision_copies_configuration_but_leaves_the_source_alone(solar_env):
    with solar_state.session() as store:
        source = store.task_create(
            [("title", '"Weekly AI News"'), ("object", '"old"'), ("scope", '"s"'), ("effect", '"e"'),
             ("planet", '"marketing"'), ("scheduled_time", '"09:00"'), ("recurring", "true"),
             ("recurring_last_run", '"2027-01-01T00:00:00Z"'), ("recurring_run_count", "9")],
            "\n# Weekly AI News\n\nOld steps.\n## Result\n\nold output\n", status="queued")
        before = store.task_export(source)
    made = run("task.create", dict(title="Weekly AI News (Friday)", instructions="New steps.",
                                   revises_task_id=source, effect="new effect"))
    draft = stored(made["id"])
    values = {k: solar_state.value_of(v) for k, v in draft["frontmatter"]}
    assert made["source_unchanged"] and draft["status"] == "draft"
    assert values["planet"] == "marketing" and values["scope"] == "s" and values["object"] == "old"
    assert values["effect"] == "new effect" and values["revises_task_id"] == source
    assert "recurring_last_run" not in values and "recurring_run_count" not in values
    assert "New steps." in draft["body"] and "old output" not in draft["body"]
    with solar_state.read_session() as store:
        assert store.task_export(source) == before
    refuse("task.approve", dict(task_id=made["id"], expected_row_version=draft["row_version"]),
           "task_state_refused")
    src_version = stored(source)["row_version"]
    run("task.archive", dict(task_id=source, expected_row_version=src_version, reason="replaced"))
    run("task.approve", dict(task_id=made["id"], expected_row_version=draft["row_version"]))
    assert stored(made["id"])["status"] == "queued" and stored(source)["status"] == "archived"


def test_a_local_executor_task_is_not_revised_through_mcp(solar_env):
    with solar_state.session() as store:
        source = store.task_create(
            [("title", '"Local"'), ("executor", "local"), ("local_command", '"bash x.sh"')],
            "\n# Local\n", status="queued")
    refuse("task.create", dict(title="Rev", instructions="x", revises_task_id=source), "revision_unsupported")
    refuse("task.create", dict(title="Rev", instructions="x", revises_task_id="nope"), "task_not_found")


def test_executor_settings_cannot_be_set_at_all(solar_env):
    for key in ("executor", "local_command", "local_timeout", "command", "path"):
        body, error = execute("task.create", dict(title="X", instructions="x", **{key: "bash x.sh"}))
        assert error and body["code"] == "invalid_arguments", key


# --------------------------------------------------------------------------
# revisions keep the source's restrictions
# --------------------------------------------------------------------------

def test_a_revision_keeps_restrictions_destination_and_resource_hooks(solar_env):
    with solar_state.session() as store:
        source = store.task_create(
            [("title", '"Voice prep"'), ("origin_channel", "voice"), ("origin_chat_id", '"111"'),
             ("origin_request_id", '"req-1"'), ("origin_thread_id", '"th-1"'), ("notify_when", "completed"),
             ("resources", '"browser,db"'), ("cleanup_required", "true"), ("cleanup_timeout", "45")],
            "\n# Voice prep\n\nRead only.\n", status="queued")
    made = run("task.create", dict(title="Revised", instructions="x", revises_task_id=source))
    values = {k: solar_state.value_of(v) for k, v in stored(made["id"])["frontmatter"]}
    # The read-only executor path is chosen by origin_channel; the destination by origin_chat_id.
    assert values["origin_channel"] == "voice" and values["origin_chat_id"] == "111"
    assert values["resources"] == "browser,db" and values["cleanup_required"] == "true"
    assert values["cleanup_timeout"] == "45" and values["notify_when"] == "completed"
    # One request's identity is not inherited: the queue de-duplicates on it.
    assert not {"origin_request_id", "origin_thread_id", "origin_run_id"} & set(values)
    # Two sources with different chats never cross over.
    with solar_state.session() as store:
        other = store.task_create([("title", '"B"'), ("origin_chat_id", '"222"'), ("notify_when", "completed")],
                                  "\n# B\n", status="queued")
    again = run("task.create", dict(title="B2", instructions="x", revises_task_id=other))
    assert {k: solar_state.value_of(v) for k, v in stored(again["id"])["frontmatter"]}["origin_chat_id"] == "222"


def test_restrictions_are_part_of_what_is_approved(solar_env):
    import solar_state as state
    base = [["title", ' "T"']]
    assert state.material_digest(base, "b") != state.material_digest(base + [["origin_channel", " voice"]], "b")
    assert state.material_digest(base, "b") != state.material_digest(base + [["resources", ' "db"']], "b")
    assert state.material_digest(base, "b") != state.material_digest(base + [["origin_chat_id", ' "1"']], "b")


# --------------------------------------------------------------------------
# legacy "scheduled_time: now" and one serialization
# --------------------------------------------------------------------------

def test_a_task_queued_with_scheduled_time_now_can_be_revised_and_made_recurring(solar_env):
    with solar_state.session() as store:
        source = store.task_create([("title", '"Queued now"'), ("scheduled_time", '"now"'), ("recurring", "false")],
                                   "\n# Queued now\n", status="queued")
    made = run("task.create", dict(title="Revision", instructions="x", revises_task_id=source))
    # Only the recurrence changes: "now" is no clock time, so no zone is demanded and nothing crashes.
    out = run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"], recurring=True))
    assert out["schedule"]["next_occurrences"] == [] and out["status"] == "draft"
    detail = search(scope="tasks", task_id=made["id"])
    assert detail["schedule"]["time"] == "now" and "next_occurrences" not in detail["schedule"]
    # A real clock time on top of it still needs a zone.
    body, error = execute("task.schedule", dict(task_id=made["id"], expected_row_version=out["row_version"],
                                                scheduled_time="17:00"))
    assert error and body["code"] == "schedule_invalid"


def test_weekdays_are_refused_without_a_real_hour_when_the_task_inherited_now(solar_env):
    """Fridays on top of "now" would be stored but still run on any day: refuse, change nothing."""
    with solar_state.session() as store:
        source = store.task_create([("title", '"Queued now"'), ("scheduled_time", '"now"')],
                                   "\n# Queued now\n", status="queued")
    made = run("task.create", dict(title="Revision", instructions="x", revises_task_id=source))
    before = stored(made["id"])
    for arguments in (dict(scheduled_weekdays=[5], scheduled_timezone=MADRID),
                      dict(scheduled_weekdays=[5])):
        body, error = execute("task.schedule", dict(task_id=made["id"],
                                                    expected_row_version=made["row_version"], **arguments))
        assert error and body["code"] == "schedule_invalid", arguments
    after = stored(made["id"])
    assert after["row_version"] == before["row_version"] and after["frontmatter"] == before["frontmatter"]
    # With a real HH:MM the same days are accepted and replace "now".
    out = run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                    scheduled_time="17:00", scheduled_weekdays=[5], scheduled_timezone=MADRID))
    assert search(scope="tasks", task_id=made["id"])["schedule"]["time"] == "17:00"
    assert out["status"] == "draft"


def test_the_digest_does_not_depend_on_how_a_value_was_quoted(solar_env):
    """Written by task.schedule or by a shell script: same meaning, same digest."""
    made = new_task()
    out = run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                    scheduled_time="17:00", scheduled_weekdays=[5], scheduled_timezone=MADRID,
                                    recurring=True, recurring_max_runs=3))
    task = stored(made["id"])
    quoted = [[k, v] for k, v in task["frontmatter"]]
    bare = [[k, (" " + solar_state.value_of(v)) if k in ("scheduled_time", "scheduled_timezone", "scheduled_weekdays")
             else v] for k, v in quoted]
    swapped = [[k, ' "true"' if k == "recurring" else (' "3"' if k == "recurring_max_runs" else v)] for k, v in bare]
    assert out["digest"] == solar_state.material_digest(quoted, task["body"])
    assert solar_state.material_digest(quoted, task["body"]) == solar_state.material_digest(bare, task["body"])
    assert solar_state.material_digest(bare, task["body"]) == solar_state.material_digest(swapped, task["body"])
    # Round trip through approve: the recorded digest is the one reported before.
    approved = run("task.approve", dict(task_id=made["id"], expected_row_version=out["row_version"]))
    assert approved["approved_digest"] == out["digest"]


def test_every_frontmatter_value_comes_from_one_serializer(solar_env):
    import operations as ops
    assert [ops._fm(v) for v in (True, False, 3, "a b", 'q"x')] == ["true", "false", "3", '"a b"', '"q\\"x"']


# --------------------------------------------------------------------------
# result view reads the executor's log
# --------------------------------------------------------------------------

def test_result_view_returns_the_executor_log_when_the_body_has_no_result(solar_env):
    logs = solar_env.runtime / "task-logs"
    logs.mkdir(parents=True)
    log = logs / "run.md"
    log.write_text("# Async Task Execution\n\n- outcome: success\n\n## Result\n\nThe finished report.\n")
    outside = solar_env.tmp_path / "outside.md"
    outside.write_text("## Result\n\nsecret\n")
    with solar_state.session() as store:
        ok = store.task_create([("title", '"Done"'), ("result_path", json.dumps(str(log)))], "\n# Done\n", status="draft")
        bad = store.task_create([("title", '"Bad"'), ("result_path", json.dumps(str(outside)))], "\n# Bad\n", status="draft")
        link = logs / "link.md"
        link.symlink_to(outside)
        linked = store.task_create([("title", '"L"'), ("result_path", json.dumps(str(link)))], "\n# L\n", status="draft")
    good = search(scope="tasks", task_id=ok, view="result")
    assert good["recorded"] is True and good["results"] == []
    assert good["execution_log"]["text"].startswith("## Result") and "finished report" in good["execution_log"]["text"]
    for task_id in (bad, linked):
        refused = search(scope="tasks", task_id=task_id, view="result")
        assert refused["recorded"] is False and refused["execution_log"] is None


def test_result_view_falls_back_to_the_recorded_log_path_and_stays_confined(solar_env):
    logs = solar_env.runtime / "task-logs"
    logs.mkdir(parents=True)
    log = logs / "by-log-path.md"
    log.write_text("# Async Task Execution\n\n## Error\n\n- error_code: boom\n")
    big = logs / "big.md"
    big.write_text("## Result\n\n" + "x" * 70000)
    outside = solar_env.tmp_path / "elsewhere.md"
    outside.write_text("## Result\n\nsecret\n")
    with solar_state.session() as store:
        by_log = store.task_create([("title", '"A"')], "\n# A\n", status="draft")
        store.task_record(by_log, log_path=str(log))
        huge = store.task_create([("title", '"B"')], "\n# B\n", status="draft")
        store.task_record(huge, log_path=str(big))
        escaped = store.task_create([("title", '"C"'), ("result_path", json.dumps(str(outside)))],
                                    "\n# C\n", status="draft")
        store.task_record(escaped, log_path=str(outside))
    found = search(scope="tasks", task_id=by_log, view="result")["execution_log"]
    assert found["outcome"] == "error" and "boom" in found["text"] and found["file"] == "by-log-path.md"
    capped = search(scope="tasks", task_id=huge, view="result")["execution_log"]
    assert capped["truncated"] is True and len(capped["text"].encode()) <= 60000
    assert search(scope="tasks", task_id=escaped, view="result")["execution_log"] is None
