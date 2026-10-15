"""task.return_to_draft and the rename of a queued task, through solar_execute."""
from __future__ import annotations

import json

import mcp_approve
import operations
import solar_state
from mcp_helpers import call, execute, new_task, run, search, stored
from test_task_operations import refuse


def approved_task(title="Weekly", instructions="Do the work.", **extra):
    made = new_task(title, instructions, **extra)
    run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    return made["id"]


def values(task_id):
    return {k: solar_state.value_of(v) for k, v in stored(task_id)["frontmatter"]}


def row_count():
    with solar_state.session() as store:
        return len(store.task_list())


def test_return_to_draft_keeps_the_task_and_withdraws_the_approval(solar_env):
    task_id = approved_task()
    approved = values(task_id)["approved_digest"]
    rows = row_count()
    task = stored(task_id)
    out = run("task.return_to_draft", dict(task_id=task_id, expected_row_version=task["row_version"]))
    after = stored(task_id)
    assert out["returned"] is True and out["status"] == "draft" and out["queued"] is False
    assert out["needs_approval"] is True and out["activated"] is False
    assert after["status"] == "draft" and after["body"] == task["body"] and row_count() == rows
    assert not any(key.startswith("approved_") for key in values(task_id))
    with solar_state.session() as store:
        assert store.task_claim_next("w") is None
        withdrawn = store.audit_rows("task_approval_withdrawn")[-1]
    assert withdrawn["task_id"] == task_id and withdrawn["approved_digest"] == approved
    assert withdrawn["actor"] == "mcp:task.return_to_draft"
    history = search(scope="tasks", task_id=task_id, view="history")
    assert [e["to_status"] for e in history["events"]][-2:] == ["queued", "draft"]


def test_return_to_draft_then_approve_queues_it_again_with_a_new_digest(solar_env):
    task_id = approved_task()
    out = run("task.return_to_draft", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"]))
    edited = run("task.update", dict(task_id=task_id, expected_row_version=out["row_version"],
                                     instructions="Changed steps."))
    run("task.approve", dict(task_id=task_id, expected_row_version=edited["row_version"]))
    with solar_state.session() as store:
        assert store.task_claim_next("w")["id"] == task_id


def test_return_to_draft_refuses_stale_versions_and_other_states(solar_env):
    task_id = approved_task()
    version = stored(task_id)["row_version"]
    refuse("task.return_to_draft", dict(task_id=task_id, expected_row_version=version + 1), "task_changed")
    assert stored(task_id)["status"] == "queued"
    with solar_state.session() as store:
        store.task_claim(task_id, "w")
    refuse("task.return_to_draft", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"]),
           "task_state_refused")
    draft = new_task()
    refuse("task.return_to_draft", dict(task_id=draft["id"], expected_row_version=draft["row_version"]),
           "task_state_refused")
    refuse("task.return_to_draft", dict(task_id="missing", expected_row_version=1), "task_state_refused")


def test_return_to_draft_needs_an_approval_of_its_exact_call(solar_env):
    task_id = approved_task()
    version = stored(task_id)["row_version"]
    op = operations.OPERATIONS["task.return_to_draft"]
    assert op.authority == operations.OPERATIONS["task.cancel"].authority
    body, error = execute("task.return_to_draft", dict(task_id=task_id, expected_row_version=version),
                          approved=False)
    assert error and body["refused"]["code"] == "approval_required"
    granted = mcp_approve.grant("task.return_to_draft",
                                dict(task_id=task_id, expected_row_version=version), 900, "t")
    for changed in (dict(task_id=task_id, expected_row_version=version + 1),
                    dict(task_id=new_task()["id"], expected_row_version=version)):
        body, error = call("solar_execute", dict(operation="task.return_to_draft", arguments=changed,
                                                 approval_id=granted["approval_id"]))
        assert error and body["refused"]["code"] == "approval_scope_mismatch", changed
    assert stored(task_id)["status"] == "queued"
    # An approval for another operation never runs this one.
    other = mcp_approve.grant("task.cancel", dict(task_id=task_id, expected_row_version=version), 900, "t")
    body, error = call("solar_execute", dict(operation="task.return_to_draft",
                                             arguments=dict(task_id=task_id, expected_row_version=version),
                                             approval_id=other["approval_id"]))
    assert error and stored(task_id)["status"] == "queued"
    body, error = execute("task.return_to_draft", dict(task_id=task_id, expected_row_version=version,
                                                       command="rm -rf /"))
    assert error and body["code"] == "invalid_arguments"


def test_renaming_a_queued_task_keeps_its_id_place_and_approval(solar_env):
    task_id = approved_task("Juan", "Call Juan.")
    before = stored(task_id)
    approved = values(task_id)["approved_digest"]
    rows = row_count()
    out = run("task.update", dict(task_id=task_id, expected_row_version=before["row_version"],
                                  title="Sales follow-up"))
    after = stored(task_id)
    assert out["status"] == "queued" and out["needs_approval"] is False and out["activated"] is False
    assert after["title"] == "Sales follow-up" and after["body"].startswith("\n# Sales follow-up\n")
    assert after["body"].endswith(before["body"].split("\n", 3)[3])
    assert values(task_id)["approved_digest"] == approved and row_count() == rows
    assert out["digest"] == approved
    with solar_state.session() as store:
        renamed = store.audit_rows("task_renamed")[-1]
        assert renamed["from_title"] == "Juan" and renamed["to_title"] == "Sales follow-up"
        assert store.audit_rows("approval_digest_mismatch") == []
        assert store.task_claim_next("w")["id"] == task_id


def test_renaming_a_queued_error_does_not_requeue_it(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"Boom"')], "\n# Boom\n\nSteps.\n", status="queued")
        store.task_claim_next("w")
        store.task_fail(task_id, "\n## Execution Error\n\nboom\n")
    body, error = execute("task.update", dict(task_id=task_id, title="Renamed",
                                              expected_row_version=stored(task_id)["row_version"]))
    assert error and body["code"] == "task_not_editable"
    assert stored(task_id)["status"] == "error" and "boom" in stored(task_id)["body"]


def test_any_other_edit_of_a_queued_task_is_refused_until_it_is_returned_to_draft(solar_env):
    task_id = approved_task()
    version = stored(task_id)["row_version"]
    approved = values(task_id)["approved_digest"]
    for operation, extra in (("task.update", dict(instructions="Swapped after approval.")),
                             ("task.update", dict(effect="wider")),
                             ("task.schedule", dict(scheduled_time="17:00", scheduled_timezone="Europe/Madrid",
                                                    scheduled_weekdays=[5]))):
        refuse(operation, dict(task_id=task_id, expected_row_version=version, **extra), "task_not_editable")
    after = stored(task_id)
    assert after["row_version"] == version and values(task_id)["approved_digest"] == approved


def test_a_local_executor_task_is_not_revised_and_rename_adds_no_permission(solar_env):
    with solar_state.session() as store:
        local = store.task_create(
            [("title", '"Local"'), ("executor", "local"), ("local_command", '"bash x.sh"')],
            "\n# Local\n", status="queued")
    body, error = execute("task.create", dict(title="Rev", instructions="x", revises_task_id=local))
    assert error and body["code"] == "revision_unsupported"
    for key in ("executor", "local_command", "approved_digest", "approved_definition"):
        body, error = execute("task.update", dict(task_id=local, expected_row_version=1, **{key: "x"}))
        assert error and body["code"] == "invalid_arguments", key
    before = values(local)
    run("task.update", dict(task_id=local, expected_row_version=stored(local)["row_version"], title="Local 2"))
    after = values(local)
    assert after["executor"] == before["executor"] and after["local_command"] == before["local_command"]
    assert after["approved_digest"] == before["approved_digest"]


def test_the_rename_approval_text_says_nothing_is_requeued(solar_env):
    import approval_text
    task_id = approved_task()
    version = stored(task_id)["row_version"]
    text, _ = approval_text.render("task.update", dict(task_id=task_id, expected_row_version=version,
                                                       title="New name"), seconds=60, lang="en")
    assert "only the title changes" in text
    text, _ = approval_text.render("task.update", dict(task_id=task_id, expected_row_version=version,
                                                       instructions="Other."), seconds=60, lang="en")
    assert "Return it to draft first" in text
    text, _ = approval_text.render("task.return_to_draft", dict(task_id=task_id, expected_row_version=version),
                                   seconds=60, lang="en")
    assert "approval is withdrawn" in text and "Return task to draft" in text
    assert task_id not in text
    es, _ = approval_text.render("task.return_to_draft", dict(task_id=task_id, expected_row_version=version),
                                 seconds=60, lang="es")
    assert "Devolver tarea a borrador" in es


def test_the_new_operation_is_documented_and_listed(solar_env):
    rows = search(scope="operations")["operations"]
    assert "task.return_to_draft" in {row["name"] for row in rows}
    assert json.dumps(rows)
