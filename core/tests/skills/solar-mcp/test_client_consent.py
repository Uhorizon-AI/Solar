"""The client's tool permission is the consent for task lifecycle operations; risk decides at the claim.

This module tests the operations as they ship (CLIENT_CONSENT = True keeps the conftest from putting the
form back). Creating, editing, scheduling, queueing, cancelling and archiving a task ask nothing; a task whose
execution is not confined to a verified read-only profile waits (awaiting_approval) for task.authorize_run,
the one step left with a form. Nothing here reaches a provider or a service.
"""
from __future__ import annotations

import json

import pytest

import mcp_approve
import mcp_server
import operations
import solar_state
from mcp_helpers import call, docs, execute, run, search, stored

CLIENT_CONSENT = True


def ask(operation, arguments):
    return call("solar_execute", dict(operation=operation, arguments=arguments))


def make(title="Work", **extra):
    body, error = ask("task.create", dict(title=title, instructions="Do it.", **extra))
    assert not error, body
    return body["result"]


def claim(task_id):
    with solar_state.session() as store:
        return store.task_claim_detail(task_id, "worker")


class _EveryProvider:
    def __contains__(self, _):
        return True


@pytest.fixture
def every_provider_verified(monkeypatch):
    """Negative cases only: pretends every provider has a verified implementation of the profile. The
    positive case uses the registry that ships."""
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {"repository_readonly_v1": _EveryProvider()})


def confine(task_id, mode="read", profile="repository_readonly_v1", provider="codex"):
    """What the review composition stores: a profile and a declared access."""
    access = json.dumps(dict(version=1, mode=mode, scopes=["/tmp/repo"], resources=[]), sort_keys=True,
                        separators=(",", ":"))
    with solar_state.session() as store:
        store.task_set(task_id, "execution_profile", json.dumps(profile))
        store.task_set(task_id, "access_policy", access)
        store.task_set(task_id, "provider", json.dumps(provider))


# -- no form for the lifecycle ---------------------------------------------------------------------

LIFECYCLE = ("task.create", "task.update", "task.schedule", "task.approve", "task.return_to_draft",
             "task.cancel", "task.requeue", "task.archive")


def test_the_lifecycle_operations_ride_on_the_clients_permission():
    for name in LIFECYCLE:
        op = operations.OPERATIONS[name]
        assert op.client_consent and op.authority == "A2" and not op.external_communication, name
    for name in ("task.authorize_run", "async_execution.propose", "async_execution.apply", "telegram.send"):
        assert not operations.OPERATIONS[name].client_consent, name


def test_creating_and_queueing_ask_for_no_approval_and_leave_the_decision_in_the_log(solar_env):
    made = make("No form")
    assert made["status"] == "draft"
    body, error = ask("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert not error and body["verdict"]["code"] == "client_consent" and body["result"]["to_status"] == "queued"
    assert not mcp_approve.listing(), "no approval record was minted"
    rows = [json.loads(l) for l in solar_env.gate_audit.read_text().splitlines()]
    decisions = [r for r in rows if r.get("kind") == "decision" and r["tool"] == "task.approve"]
    assert decisions[-1]["allowed"] and decisions[-1]["code"] == "client_consent"
    assert decisions[-1]["arguments"]["task_id"] == made["id"]


def test_the_server_never_asks_a_form_for_them(solar_env):
    forms = []

    def confirm(name, arguments, request_id):
        forms.append(name)
        return True

    message = dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(
        name="solar_execute", arguments=dict(operation="task.create", arguments=dict(title="X", instructions="y"))))
    response = mcp_server.handle(message, confirm)
    assert not response["result"]["isError"] and forms == []


def test_operations_that_leave_the_machine_or_change_capacity_still_need_a_form(solar_env):
    for operation, arguments in (("async_execution.propose", dict(global_capacity=3)),
                                 ("telegram.send", dict(text="hi", chat_id="1")),
                                 ("task.authorize_run", dict(task_id="t", expected_row_version=1))):
        body, error = ask(operation, arguments)
        assert error and body["refused"]["code"] == "approval_required", operation


def test_a_forged_flag_or_an_a3_mandate_does_not_change_that(solar_env):
    body, error = ask("task.create", dict(title="X", instructions="y", client_consent=True))
    assert error and body["code"] == "invalid_arguments"
    made = make("Mandate")
    body, error = ask("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"], mandate="m"))
    assert error and body["code"] == "invalid_arguments"
    body, error = ask("task.authorize_run", dict(task_id=made["id"], expected_row_version=1, mandate="m"))
    assert error and body["code"] == "invalid_arguments"


# -- queue on create -------------------------------------------------------------------------------

def test_queue_true_creates_and_queues_in_one_call_and_says_it_is_waiting_when_risky(solar_env):
    body, error = ask("task.create", dict(title="Now", instructions="Run it", queue=True))
    assert not error, body
    result = body["result"]
    assert result["status"] == "queued" and result["queued"] is True and result["risk"] == "high"
    assert result["awaiting_approval"] is True and "task.authorize_run" in result["next"]
    assert stored(result["id"])["status"] == "queued"


def test_without_queue_the_task_stays_a_draft(solar_env):
    assert make("Later")["status"] == "draft"


def test_queue_true_on_a_revision_of_a_live_task_leaves_a_draft_and_says_why(solar_env):
    first = make("First", queue=True)
    body, error = ask("task.create", dict(title="Second", instructions="again", revises_task_id=first["id"], queue=True))
    assert not error
    assert body["result"]["status"] == "draft" and body["result"]["queued"] is False
    assert "can still run" in body["result"]["queue_refused"]


# -- the risk decides at the claim -------------------------------------------------------------------

def test_a_task_that_is_not_confined_waits_for_authorization_and_runs_after_it(solar_env):
    made = make("Free", queue=True)
    first = claim(made["id"])
    assert not first["claimed"] and first["reason"] == "awaiting_approval"
    detail = search(scope="tasks", task_id=made["id"], view="detail")
    assert detail["risk"] == "high" and detail["awaiting_approval"] is True
    body, error = ask("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert error and body["refused"]["code"] == "approval_required"        # the form is what is left
    authorized = execute("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]))[0]
    assert authorized["result"]["authorized"] is True and authorized["result"]["risk"] == "high"
    assert claim(made["id"])["claimed"]


def test_the_shipped_registry_confines_the_repository_profile_for_every_reader_provider():
    assert solar_state.VERIFIED_PROFILES["repository_readonly_v1"] >= {"claude", "codex", "agent"}


def test_a_task_confined_to_a_verified_read_only_profile_runs_without_asking(solar_env):
    made = make("Review", provider="codex")
    confine(made["id"])
    body, error = ask("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    assert not error
    detail = search(scope="tasks", task_id=made["id"], view="detail")
    assert detail["risk"] == "low" and detail["awaiting_approval"] is False
    assert claim(made["id"])["claimed"]


@pytest.mark.parametrize("mode,profile,provider", [("write", "repository_readonly_v1", "codex"),
                                                  ("read", "unknown_profile_v1", "codex")])
def test_a_declared_profile_the_executor_does_not_enforce_is_not_low_risk(solar_env, every_provider_verified, mode, profile, provider):
    made = make("Claims to be safe", provider=provider)
    confine(made["id"], mode=mode, profile=profile, provider=provider)
    ask("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    assert search(scope="tasks", task_id=made["id"], view="detail")["risk"] == "high"
    assert claim(made["id"])["reason"] == "awaiting_approval"


def test_a_provider_without_a_verified_implementation_is_high_risk(solar_env, monkeypatch):
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {"repository_readonly_v1": frozenset({"claude"})})
    made = make("Wrong provider", provider="codex")
    confine(made["id"], provider="codex")
    ask("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    assert claim(made["id"])["reason"] == "awaiting_approval"


def test_editing_after_authorization_withdraws_it_with_the_approval(solar_env):
    made = make("Edit me", queue=True)
    execute("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    current = stored(made["id"])
    run("task.update", dict(task_id=made["id"], expected_row_version=current["row_version"], instructions="Different."))
    fields = {k: v for k, v in stored(made["id"])["frontmatter"]}
    assert stored(made["id"])["status"] == "draft" and "run_authorized_digest" not in fields
    ask("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    assert claim(made["id"])["reason"] == "awaiting_approval"


def test_tasks_approved_before_the_marker_or_by_local_scripts_keep_working(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([("title", json.dumps("Legacy")), ("priority", "normal")], "\n# Legacy\n\nx\n")
        store.task_approve(task_id, actor="local-script")             # no consent marker
    assert claim(task_id)["claimed"]


def test_authorizing_needs_a_queued_task_with_a_valid_approval(solar_env):
    draft = make("Not queued")
    body, error = execute("task.authorize_run", dict(task_id=draft["id"], expected_row_version=draft["row_version"]))
    assert error and body["code"] == "task_state_refused"
    queued = make("Stale", queue=True)
    body, error = execute("task.authorize_run", dict(task_id=queued["id"], expected_row_version=queued["row_version"] + 5))
    assert error and body["code"] == "task_changed"


def test_the_waiting_reason_is_shown_as_an_authorization_wait():
    import runtime_views
    assert runtime_views.wait_kind("awaiting_approval") == "authorization"


# -- what survives edits, repeats and errors ---------------------------------------------------------

def authorized(title="Auth", **extra):
    made = make(title, queue=True, **extra)
    execute("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    return made["id"]


def test_a_pure_rename_keeps_the_authorization_and_the_task_stays_claimable(solar_env):
    task_id = authorized("Old name")
    run("task.update", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"], title="New name"))
    fields = {k: v for k, v in stored(task_id)["frontmatter"]}
    assert stored(task_id)["status"] == "queued" and "run_authorized_digest" in fields
    assert claim(task_id)["claimed"]


@pytest.mark.parametrize("change", [dict(provider="claude"), dict(access_policy=dict(mode="read", scopes=["/tmp/x"]))])
def test_changing_who_runs_it_or_what_it_may_touch_withdraws_the_authorization(solar_env, change):
    task_id = authorized("Change me")
    run("task.update", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"], **change))
    fields = {k: v for k, v in stored(task_id)["frontmatter"]}
    assert stored(task_id)["status"] == "draft" and "run_authorized_digest" not in fields
    run("task.approve", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"]))
    assert claim(task_id)["reason"] == "awaiting_approval"


def test_a_recurring_task_keeps_its_authorization_while_its_content_does_not_change(solar_env):
    made = make("Repeats")
    with solar_state.session() as store:
        store.task_set(made["id"], "recurring", "true")        # part of the content: set before queueing
    queued = run("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    run("task.authorize_run", dict(task_id=made["id"], expected_row_version=queued["row_version"]))
    with solar_state.session() as store:
        token = store.task_claim_detail(made["id"], "worker")["token"]
        store.task_complete(made["id"], token=token)
        assert store.task_status(made["id"]) == "queued"
    assert claim(made["id"])["claimed"], "the next repeat asked for a second authorization"


def test_requeueing_an_error_keeps_the_authorization_of_the_same_content(solar_env):
    task_id = authorized("Fails once")
    with solar_state.session() as store:
        token = store.task_claim_detail(task_id, "worker")["token"]
        store.task_fail(task_id, "## Execution Error\nboom", token=token)
    run("task.requeue", dict(task_id=task_id, expected_row_version=stored(task_id)["row_version"]))
    assert claim(task_id)["claimed"]


def test_approving_through_the_operation_says_when_the_task_will_wait(solar_env):
    made = make("Say it")
    result = run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert result["risk"] == "high" and result["awaiting_approval"] is True and "task.authorize_run" in result["next"]
    assert search(scope="tasks", task_id=made["id"], view="status")["awaiting_approval"] is True


def test_the_gate_audit_keeps_queue_true_and_the_consent_code(solar_env):
    ask("task.create", dict(title="Audited", instructions="x", queue=True))
    rows = [json.loads(l) for l in solar_env.gate_audit.read_text().splitlines()]
    decision = [r for r in rows if r.get("kind") == "decision" and r["tool"] == "task.create"][-1]
    assert decision["code"] == "client_consent" and decision["arguments"]["queue"] is True


def test_the_contract_of_a_client_consent_operation_does_not_promise_a_form(solar_env):
    approval = docs(id="operation:task.create")["approval"]
    assert "no form" in approval and "task.authorize_run" in approval
    assert "Native client confirmation" in docs(id="operation:task.authorize_run")["approval"]
