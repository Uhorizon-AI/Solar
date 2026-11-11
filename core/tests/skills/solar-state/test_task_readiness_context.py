"""Approval recovery and prompt context share the stored task, not caller prose."""
import json

import pytest

import solar_state
from test_approval_gate import queued, fm
from reservation_tokens import token_of


@pytest.mark.parametrize("broken", ["absent", "legacy", "mismatch"])
def test_readiness_is_read_only_and_advertises_valid_recovery(ready, broken):
    with solar_state.session() as store:
        task = queued(store)
        value = {"absent": "", "legacy": "old-digest", "mismatch": "v2:not-this-task"}[broken]
        store.task_set(task, "approved_digest", json.dumps(value))
        before = store.task_get(task)
        audit = store.audit_rows()
        info = store.task_authorization_readiness(task, expected_row_version=before["row_version"])
        assert not info["ready"] and info["content_approval"] == broken
        assert store.task_get(task) == before and store.audit_rows() == audit
        recovery = info["next_operation"]["arguments"]
        assert recovery["operation"] == "task.return_to_draft"
        store.task_return_to_draft(**recovery["arguments"])
        draft = store.task_get(task)
        assert draft["status"] == "draft"
        store.task_approve(task, expected_row_version=draft["row_version"], consent="client")
        info = store.task_authorization_readiness(task)
        assert info["ready"] and info["execution_authorization"] == "required"
        store.task_authorize_run(task, expected_row_version=info["row_version"])
        assert store.task_authorization_readiness(task)["execution_authorization"] == "satisfied"


def test_post_confirmation_edit_has_structured_refusal(ready):
    with solar_state.session() as store:
        task = queued(store)
        version = store.task_get(task)["row_version"]
        assert store.task_authorization_readiness(task, expected_row_version=version)["ready"]
        store.task_set(task, "effect", '"changed"')
        with pytest.raises(solar_state.TaskAuthorizationRefused) as exc:
            store.task_authorize_run(task, expected_row_version=version)
        assert exc.value.code == "task_changed"
        assert exc.value.readiness["next_operation"]["tool"] == "solar_search"
        assert not store.audit_rows("task_run_authorized")


def test_error_readiness_retries_valid_content_without_withdrawing_consent(ready):
    with solar_state.session() as store:
        task = queued(store)
        store.task_set(task, "approved_consent", '"client"')
        store.task_authorize_run(task, expected_row_version=store.task_get(task)["row_version"])
        consent = fm(store, task)["run_authorized_digest"]
        token = store.task_claim_detail(task, "test")["token"]
        store.task_fail(task, "\n## Execution Error\nRetry.\n", token=token)
        info = store.task_authorization_readiness(task)
        assert not info["ready"] and info["code"] == "task_state_refused"
        assert info["execution_authorization"] == "not_available"
        operation = info["next_operation"]["arguments"]
        assert operation["operation"] == "task.requeue"
        store.task_requeue(**operation["arguments"])
        assert fm(store, task)["run_authorized_digest"] == consent
        assert store.task_authorization_readiness(task)["execution_authorization"] == "satisfied"


@pytest.mark.parametrize("broken", ["absent", "legacy", "mismatch"])
def test_error_with_invalid_content_advertises_draft_recovery(ready, broken):
    with solar_state.session() as store:
        task = queued(store)
        token = store.task_claim_detail(task, "test")["token"]
        store.task_fail(task, "\n## Execution Error\nRetry.\n", token=token)
        value = {"absent": "", "legacy": "old", "mismatch": "v2:wrong"}[broken]
        store.task_set(task, "approved_digest", json.dumps(value))
        info = store.task_authorization_readiness(task)
        assert info["next_operation"]["arguments"]["operation"] == "task.return_to_draft"
        assert not info["ready"] and info["execution_authorization"] == "not_available"


@pytest.mark.parametrize("status", ["draft", "planned"])
def test_new_definition_has_no_historical_context_or_ambiguity(ready, status):
    instructions = "Instruction.\n```md\n## Result\nAuthor example.\n```"
    with solar_state.session() as store:
        task = store.task_create([("title", '"T"')], "\n# T\n\n" + instructions, status=status)
        context = store.task_definition_context(task)
        assert context == dict(instructions=instructions, context="", boundary="definition")
        assert store.task_authorization_readiness(task)["execution_authorization"] == "not_available"


@pytest.mark.parametrize("status", ["draft", "planned", "queued"])
def test_import_without_snapshot_does_not_masquerade_as_new_definition(ready, status):
    with solar_state.session() as store:
        task = store.task_import(f'---\nid: "import-{status}"\nstatus: {status}\ntitle: "T"\n---\n\nInstruction.\n## Result\nPossibly authored.\n')
        context = store.task_definition_context(task)
        assert context["boundary"] == "ambiguous" and "Possibly authored." in context["context"]


def test_error_to_draft_never_enters_queue_and_removes_all_authority(ready):
    with solar_state.session() as store:
        task = queued(store, recurring="true", recurring_run_count="3")
        store.task_set(task, "approved_consent", '"client"')   # a form-approved task is the one that needs this step
        store.task_authorize_run(task, expected_row_version=store.task_get(task)["row_version"])
        claim = store.task_claim_detail(task, "test")
        store.task_fail(task, "\n## Execution Error\n\nRetain diagnostic.\n", token=claim["token"])
        before = store.task_get(task)
        before_fields = fm(store, task)
        with pytest.raises(solar_state.TaskChanged):
            store.task_return_to_draft(task, expected_row_version=before["row_version"] - 1)
        assert store.task_get(task) == before
        events = list(store.conn.execute("SELECT * FROM task_events WHERE task_id=?", (task,)))
        out = store.task_return_to_draft(task, expected_row_version=before["row_version"])
        after = store.task_get(task)
        assert out["from_status"] == "error" and after["status"] == "draft"
        assert after["body"] == before["body"]
        assert fm(store, task)["recurring_run_count"] == "3"
        assert fm(store, task).get("recurring_last_run") == before_fields.get("recurring_last_run")
        assert store.audit_rows("task_approval_withdrawn")[-1]["task_id"] == task
        assert not (set(solar_state.APPROVAL_KEYS) & set(fm(store, task)))
        new_events = list(store.conn.execute("SELECT * FROM task_events WHERE task_id=?", (task,)))[len(events):]
        assert [(r["from_status"], r["to_status"]) for r in new_events] == [("error", "draft")]
        assert not store.task_claim_detail(task, "other")["claimed"]
        store.task_approve(task, expected_row_version=after["row_version"], consent="client")
        assert "Retain diagnostic." in solar_state.task_context(store.task_get(task))["context"]


@pytest.mark.parametrize("status", ["active", "completed", "cancelled", "archived"])
def test_recovery_refuses_nonrecoverable_states_without_changes(ready, status):
    with solar_state.session() as store:
        task = store.task_import(f'---\nid: "state-{status}"\nstatus: {status}\ntitle: "T"\n---\n\nBody.\n')
        before = store.task_get(task)
        with pytest.raises(solar_state.TransitionRefused):
            store.task_return_to_draft(task, expected_row_version=before["row_version"])
        assert store.task_get(task) == before


def test_v9_migration_adds_error_recovery_without_changing_tasks(ready):
    with solar_state.session() as store:
        task = queued(store)
        before = store.task_get(task)
        store.conn.execute("DELETE FROM transitions WHERE from_status='error' AND to_status='draft'")
        store.conn.execute("PRAGMA user_version=8")
    with solar_state.cutover(ready) as cut:
        assert cut.upgrade_schema()["to_version"] == 9
    with solar_state.session() as store:
        assert store.task_get(task) == before
        assert store.conn.execute("SELECT 1 FROM transitions WHERE from_status='error' AND to_status='draft'").fetchone()


@pytest.mark.parametrize("tail", [
    "## Result\nPrevious cycle.\n## Findings\nKeep this too.",
    "## Subtask results\nChild succeeded.\nChild failed: useful diagnosis.",
    "## Execution Error\nRetry diagnosis.",
])
def test_prompt_preserves_definition_and_generated_context_without_digest_change(ready, tail):
    instructions = "Do it.\n```md\n## Result\nThis is an instruction example.\n```"
    with solar_state.session() as store:
        task = queued(store, body="\n# T\n\n" + instructions + "\n")
        digest = fm(store, task)["approved_digest"]
        claim = store.task_claim_detail(task, "test")
        store.task_set_body(task, store.task_get(task)["body"] + "\n" + tail + "\n")
        ctx = store.task_prompt_context(task, token=claim["token"])
        assert ctx == dict(instructions=instructions, context=tail, boundary="snapshot")
        assert fm(store, task)["approved_digest"] == digest
        assert solar_state.approval_state(store.task_get(task)["frontmatter"], store.task_get(task)["body"]) is None
        with pytest.raises(solar_state.StaleToken):
            store.task_prompt_context(task, token="wrong")


def test_ambiguous_import_preserves_whole_body_as_context(ready):
    with solar_state.session() as store:
        task = queued(store)
        value = store.task_get(task)
    value["frontmatter"] = [p for p in value["frontmatter"] if p[0] not in ("approved_definition", "definition_snapshot")]
    value["body"] = "\n# T\n\nInstruction.\n\n## Result\nHistorical result.\n## Other\nAmbiguous.\n"
    ctx = solar_state.task_context(value)
    assert ctx["boundary"] == "ambiguous" and "Historical result." in ctx["context"]
    assert "Ambiguous." in ctx["context"]
