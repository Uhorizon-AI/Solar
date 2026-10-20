"""task.wait: the read-only wait operation of solar_execute.

These tests pin the plan's promises: it is A0 (no approval), it waits inside
one call up to timeout_seconds and returns the final status plus the task's
result view, it never mutates anything, a missing or malformed request is
refused, and a task that is still running returns its status and a next hint,
never an error.
"""
from __future__ import annotations

import threading

import mcp_server
import solar_state
from mcp_helpers import execute, new_task, queue_and_authorize, run
from reservation_tokens import token_of

CLIENT_CONSENT = True


def _finish(store, task_id: str, *, status: str) -> None:
    """Take an active task to a terminal status directly through the store."""
    token = token_of(store, task_id)
    if status == "completed":
        store.task_complete(task_id, token=token)
    elif status == "error":
        store.task_fail(task_id, "\n## Execution Error\n\nboom\n", token=token)
    elif status == "cancelled":
        store.task_complete(task_id, cancelled=True, token=token)
    elif status == "archived":
        store.task_complete(task_id, cancelled=True, token=token)
        store.task_transition(task_id, "archived", expected_from="cancelled")


def _activate(task_id: str) -> int:
    """Approve, authorize the run and claim it; returns the claimed row version."""
    made = stored_version_row(task_id)
    queue_and_authorize(task_id, made["row_version"])
    with solar_state.session() as store:
        store.task_claim_next("w")
        return store.task_get(task_id)["row_version"]


def stored_version_row(task_id: str) -> dict:
    with solar_state.session() as store:
        return store.task_get(task_id)


def stored_version(task_id: str) -> int:
    with solar_state.session() as store:
        return store.task_get(task_id)["row_version"]


# --------------------------------------------------------------------------
# a terminal task answers immediately, without writing
# --------------------------------------------------------------------------

def test_wait_returns_a_completed_task_with_its_result_view(solar_env):
    made = new_task()
    _activate(made["id"])
    with solar_state.session() as store:
        _finish(store, made["id"], status="completed")
        version = store.task_get(made["id"])["row_version"]
    body, error = execute("task.wait", dict(task_id=made["id"], poll_seconds=1))
    assert not error, body
    assert body["result"] == dict(id=made["id"], status="completed", row_version=version,
                                  waited=True, elapsed_seconds=0,
                                  result=dict(results=[], execution_log=None, recorded=False))


def test_wait_answers_every_terminal_status_and_never_writes(solar_env):
    for status in ("completed", "error", "cancelled", "archived"):
        made = new_task(f"T {status}", "Steps.")
        _activate(made["id"])
        with solar_state.session() as store:
            _finish(store, made["id"], status=status)
            version = store.task_get(made["id"])["row_version"]
        body, error = execute("task.wait", dict(task_id=made["id"], poll_seconds=1))
        assert not error, (status, body)
        assert body["result"]["status"] == status
        assert body["result"]["row_version"] == version          # a read bumps nothing
        assert body["result"]["waited"] is True and body["result"]["elapsed_seconds"] == 0


def test_wait_carries_the_executor_log_in_the_result_view(solar_env):
    import json
    made = new_task("Logged", "Write the report.")
    _activate(made["id"])
    log = solar_env.runtime / "task-logs" / "waited.md"
    log.parent.mkdir(parents=True)
    log.write_text("# Async Task Execution\n\n- outcome: success\n\n## Result\n\nThe finished report.\n")
    with solar_state.session() as store:
        store.task_set(made["id"], "result_path", json.dumps(str(log)))
        _finish(store, made["id"], status="completed")
    body, error = execute("task.wait", dict(task_id=made["id"], poll_seconds=1))
    assert not error, body
    result = body["result"]["result"]
    assert result["recorded"] is True and result["results"] == []
    assert result["execution_log"]["outcome"] == "result"
    assert "finished report" in result["execution_log"]["text"]


# --------------------------------------------------------------------------
# a task still in flight: status plus next, never an error
# --------------------------------------------------------------------------

def test_wait_on_a_running_task_returns_status_and_next_without_error(solar_env):
    made = new_task()
    _activate(made["id"])
    body, error = execute("task.wait", dict(task_id=made["id"], timeout_seconds=1,
                                            poll_seconds=1))
    assert not error, body
    assert body["result"]["status"] == "active" and body["result"]["waited"] is False
    assert body["result"]["timeout_seconds"] == 1
    assert "task.wait" in body["result"]["next"]
    assert body["result"]["row_version"] == stored_version(made["id"])


def test_wait_answers_when_the_task_reaches_a_terminal_status_while_waiting(solar_env):
    """The slice loop re-reads the row: a task completing during the wait answers
    with the final status inside the same call."""
    made = new_task()
    _activate(made["id"])

    def finish_later():
        with solar_state.session() as store:
            _finish(store, made["id"], status="completed")

    thread = threading.Thread(target=finish_later)
    thread.start()
    body, error = execute("task.wait", dict(task_id=made["id"], timeout_seconds=10,
                                            poll_seconds=1))
    thread.join(10)
    assert not error, body
    assert body["result"]["status"] == "completed" and body["result"]["waited"] is True


def test_wait_waits_for_a_cancel_requested_task_to_land(solar_env):
    """Cancellation of an active task keeps it active until the worker stops it;
    a waiter sees the terminal status only when the transition happens."""
    made = new_task()
    _activate(made["id"])
    body, error = execute("task.wait", dict(task_id=made["id"], timeout_seconds=1,
                                            poll_seconds=1))
    assert not error and body["result"]["status"] == "active"
    version = stored_version(made["id"])
    with solar_state.session() as store:
        store.task_complete(made["id"], cancelled=True, token=token_of(store, made["id"]))
    body, error = execute("task.wait", dict(task_id=made["id"], poll_seconds=1))
    assert not error and body["result"]["status"] == "cancelled"
    assert body["result"]["row_version"] > version


# --------------------------------------------------------------------------
# refusals: read-only, so the only failures are bad requests
# --------------------------------------------------------------------------

def test_wait_refuses_a_missing_task(solar_env):
    body, error = execute("task.wait", dict(task_id="no-such-task", poll_seconds=1))
    assert error and body["code"] == "task_not_found"


def test_wait_refuses_an_empty_task_id(solar_env):
    body, error = execute("task.wait", dict(task_id=""))
    assert error and body["code"] == "invalid_arguments"


def test_wait_needs_a_task_id(solar_env):
    body, error = execute("task.wait", dict(timeout_seconds=1))
    assert error and body["code"] == "invalid_arguments"


def test_wait_rejects_an_out_of_range_timeout_or_poll(solar_env):
    made = new_task()
    for arguments in (dict(task_id=made["id"], timeout_seconds=0),
                      dict(task_id=made["id"], timeout_seconds=601),
                      dict(task_id=made["id"], poll_seconds=0),
                      dict(task_id=made["id"], poll_seconds=31)):
        body, error = execute("task.wait", arguments)
        assert error and body["code"] == "invalid_arguments", arguments


# --------------------------------------------------------------------------
# what the server announces and what the gate records
# --------------------------------------------------------------------------

def test_wait_is_offered_through_solar_execute_and_named_in_its_description(solar_env):
    from mcp_helpers import docs
    contract = docs(id="operation:task.wait")
    assert contract["operation"] == "task.wait"
    assert contract["authority"] == "A0"
    assert "task.wait" in mcp_server.TOOLS["solar_execute"]["description"]
    assert "task.wait" not in mcp_server.LEGACY_TOOLS


def test_wait_runs_on_the_gate_as_a_read(solar_env):
    execute("task.wait", dict(task_id="no-such-task"))
    import json
    rows = [json.loads(line) for line in solar_env.gate_audit.read_text().splitlines()]
    decision = [row for row in rows if row.get("kind") == "decision"
                and row.get("tool") == "task.wait"][-1]
    assert decision["allowed"] is True and decision["code"] == "read_allowed"
    assert decision["authority"] == "A0"