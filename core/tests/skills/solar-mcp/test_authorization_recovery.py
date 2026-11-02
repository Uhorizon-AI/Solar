"""One useful native confirmation, only after the stored task is ready."""
import json
import queue
import threading
from dataclasses import replace
from io import StringIO

import pytest

import approval_text
import mcp_approve
import mcp_server
import solar_state
import operations
from mcp_context import OperationError
from mcp_helpers import execute, run, search, stored
from test_client_consent import confine

CLIENT_CONSENT = True


def work():
    return run("task.create", dict(title="Work", instructions="Approved instructions.", queue=True))


def request(task, version):
    return dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(name="solar_execute",
        arguments=dict(operation="task.authorize_run", arguments=dict(task_id=task, expected_row_version=version))))


def payload(response):
    return json.loads(response["result"]["content"][0]["text"])


@pytest.mark.parametrize("problem", ["absent", "legacy", "mismatch", "draft", "stale", "missing"])
def test_invalid_prerequisite_never_opens_form_or_grants(solar_env, problem):
    made = work()
    task = made["id"]
    with solar_state.session() as store:
        if problem in ("absent", "legacy", "mismatch"):
            store.task_set(task, "approved_digest", json.dumps(
                {"absent": "", "legacy": "old", "mismatch": "v2:wrong"}[problem]))
        elif problem == "draft":
            store.task_return_to_draft(task, expected_row_version=stored(task)["row_version"])
    version = stored(task)["row_version"]
    if problem == "stale":
        version -= 1
    before = mcp_approve.listing()
    forms = []
    out = mcp_server.handle(request("missing" if problem == "missing" else task, version),
                            confirm=lambda *args: forms.append(args) or True)
    result = payload(out)
    assert out["result"]["isError"] and not forms
    assert not result["readiness"]["ready"] and mcp_approve.listing() == before
    rows = [json.loads(line) for line in solar_env.gate_audit.read_text().splitlines()]
    linked = [row for row in rows if row.get("trace_id") == result["trace_id"]]
    assert len(linked) == 2 and {row["kind"] for row in linked} == {"decision", "outcome"}
    assert linked[0]["allowed"] is False and linked[1]["ok"] is False
    assert not stored(task).get("run_authorized_digest")


def test_legacy_recovery_uses_one_form_and_preserves_the_task(solar_env):
    made = work(); task = made["id"]
    with solar_state.session() as store:
        store.task_set(task, "approved_digest", '"old"')
    original = stored(task)["body"]
    info = search(scope="tasks", task_id=task, view="detail")["readiness"]
    recovery = info["next_operation"]["arguments"]
    out = run(recovery["operation"], recovery["arguments"])
    run("task.approve", dict(task_id=task, expected_row_version=out["row_version"]))
    forms = []
    out = mcp_server.handle(request(task, stored(task)["row_version"]),
                            confirm=lambda *args: forms.append(args) or True)
    assert not out["result"]["isError"] and len(forms) == 1
    assert stored(task)["body"] == original
    assert search(scope="tasks", task_id=task, view="status")["readiness"]["next_operation"] is None


def test_changed_task_after_acceptance_returns_recovery_not_transport_failure(solar_env):
    made = work(); task = made["id"]
    def accept(*args):
        with solar_state.session() as store:
            store.task_set(task, "effect", '"changed while form was open"')
        return True
    out = mcp_server.handle(request(task, stored(task)["row_version"]), confirm=accept)
    result = payload(out)
    assert out["result"]["isError"] and result["code"] == "task_changed"
    assert result["readiness"]["next_operation"]["tool"] == "solar_search"
    with solar_state.session() as store:
        assert not store.audit_rows("task_run_authorized")


@pytest.mark.parametrize("confined", [False, True])
def test_covered_consent_never_opens_another_form(solar_env, confined):
    if confined:
        made = run("task.create", dict(title="Review", instructions="Read.", provider="codex"))
        task = made["id"]
        confine(task)
        run("task.approve", dict(task_id=task, expected_row_version=stored(task)["row_version"]))
    else:
        made = work(); task = made["id"]
        out = mcp_server.handle(request(task, stored(task)["row_version"]), confirm=lambda *args: True)
        assert not out["result"]["isError"]
    before = stored(task)
    grants = mcp_approve.listing()
    forms = []
    out = mcp_server.handle(request(task, before["row_version"]),
                            confirm=lambda *args: forms.append(args) or True)
    info = payload(out)
    assert info["code"] == "task_authorization_not_required" and not forms
    assert info["readiness"]["execution_authorization"] == "satisfied"
    assert info["readiness"]["next_operation"] is None
    assert stored(task) == before and mcp_approve.listing() == grants


def test_host_approved_path_without_elicitation_still_validates(solar_env):
    made = work(); task = made["id"]
    with solar_state.session() as store:
        store.task_set(task, "approved_digest", '"legacy"')
    out, error = execute("task.authorize_run", dict(task_id=task, expected_row_version=stored(task)["row_version"]))
    assert error and out["readiness"]["content_approval"] == "legacy"
    assert not out["readiness"]["ready"]


def test_unavailable_preflight_has_stable_diagnostic_and_no_form(solar_env, monkeypatch):
    made = work()
    def unavailable(*args, **kwargs):
        raise solar_state.StateUnavailable("test cutover")
    monkeypatch.setattr(solar_state, "read_session", unavailable)
    forms = []
    out = mcp_server.handle(request(made["id"], made["row_version"]),
                            confirm=lambda *args: forms.append(args) or True)
    assert payload(out)["code"] == "state_unavailable" and not forms


def test_domain_preflight_without_details_has_same_error_envelope(solar_env, monkeypatch):
    made = work()
    def refuse(*args):
        raise OperationError("test_refusal", "No prerequisites.")
    op = operations.OPERATIONS["task.authorize_run"]
    monkeypatch.setitem(operations.OPERATIONS, op.name, replace(op, pre_confirm=refuse))
    forms = []
    out = mcp_server.handle(request(made["id"], made["row_version"]),
                            confirm=lambda *args: forms.append(args) or True)
    assert "error" not in out and out["result"]["isError"]
    assert payload(out)["code"] == "test_refusal" and payload(out)["trace_id"] and not forms


def test_form_shows_approved_definition_not_previous_results(solar_env):
    made = work(); task = made["id"]
    with solar_state.session() as store:
        store.task_set_body(task, stored(task)["body"] + "\n## Result\nDo something else from history.\n")
    text, _ = approval_text.render("task.authorize_run", dict(task_id=task, expected_row_version=stored(task)["row_version"]), seconds=120)
    assert "Approved instructions." in text and "Do something else from history." not in text


def test_new_definition_form_has_no_partial_instructions_warning(solar_env):
    made = run("task.create", dict(title="New", instructions="Author example.\n## Result\nKeep this."))
    text, _ = approval_text.render("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]), seconds=120)
    assert "Keep this." in text and "may be partial" not in text and "pueden ser parciales" not in text


@pytest.mark.parametrize("reply,outcome", [
    (dict(result=dict(action="accept", content=dict(approve=True))), "accepted"),
    (dict(result=dict(action="decline")), "declined"),
    (dict(result=dict(action="cancel")), "cancelled"),
    (dict(result=dict(action="decline", content=None)), "declined"),
    (dict(result=dict(action="cancel", content=None)), "cancelled"),
    (dict(result=dict(action="accept", content=None)), "invalid_response"),
    (dict(result=[]), "invalid_response"),
    (dict(error=dict(code=-1, message="client failed")), "client_error"),
    (None, "disconnected"),
    ("timeout", "timed_out"),
])
def test_transport_waits_for_delayed_response_and_reports_real_outcome(solar_env, monkeypatch, reply, outcome):
    made = work(); task = made["id"]
    lines = queue.Queue()
    monkeypatch.setattr(mcp_server, "CONFIRMATION_TIMEOUT", 0.05 if reply == "timeout" else 5)
    timer = None
    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=3)
                if line is None:
                    break
                yield line
    class Output(StringIO):
        def write(self, text):
            nonlocal timer
            result = super().write(text)
            message = json.loads(text)
            if message.get("method") == "elicitation/create":
                def answer():
                    if reply is None:
                        lines.put(None)
                    elif reply != "timeout":
                        lines.put(json.dumps(dict(jsonrpc="2.0", id=message["id"], **reply)))
                        lines.put(None)
                timer = threading.Timer(0.02, answer)
                timer.start()
            if message.get("method") == "notifications/cancelled":
                lines.put(None)
            return result
    lines.put(json.dumps(dict(jsonrpc="2.0", id=1, method="initialize", params=dict(capabilities=dict(elicitation={})))))
    lines.put(json.dumps(request(task, stored(task)["row_version"])))
    output = Output()
    mcp_server.serve(Input(), output)
    if timer:
        timer.join()
    messages = list(map(json.loads, output.getvalue().splitlines()))
    response = next(m for m in messages if m.get("id") == 2 and "result" in m)
    result = payload(response)
    assert result["confirmation"]["outcome"] == outcome
    with solar_state.session() as store:
        assert bool(store.audit_rows("task_run_authorized")) == (outcome == "accepted")
