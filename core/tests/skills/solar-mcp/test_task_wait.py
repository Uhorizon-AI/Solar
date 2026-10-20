"""task.wait: the read-only wait operation of solar_execute.

These tests pin the plan's promises: it is A0 (no approval), it waits inside
one call up to timeout_seconds and returns the final status plus the task's
result view, it never mutates anything, a missing or malformed request is
refused, and a task that is still running returns its status and a next hint,
never an error.
"""
from __future__ import annotations

import json
import threading
import time
from io import StringIO

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


def test_wait_answers_at_once_when_the_task_waits_for_run_authorization(solar_env):
    """A queued task that awaits `task.authorize_run` never becomes terminal by
    itself; waiting would burn the whole timeout on a state that only an
    authorization can leave."""
    made = new_task("Waiting", "Steps.")
    run("task.approve", dict(task_id=made["id"],
                             expected_row_version=stored_version(made["id"])))
    body, error = execute("task.wait", dict(task_id=made["id"], timeout_seconds=30,
                                            poll_seconds=1))
    assert not error, body
    result = body["result"]
    assert result["status"] == "queued" and result["awaiting_approval"] is True
    assert result["waited"] is False and result["elapsed_seconds"] == 0
    assert "task.authorize_run" in result["next"]


def test_wait_counts_the_time_it_actually_spent(solar_env, monkeypatch):
    """`elapsed_seconds` is wall-clock time, not the sum of the nominal slices:
    a slow read does not extend the wait past `timeout_seconds` either."""
    made = new_task()
    _activate(made["id"])
    real_sleep = time.sleep

    def slow_sleep(seconds):
        real_sleep(seconds + 0.4)          # each slice costs more than it claims

    monkeypatch.setattr(time, "sleep", slow_sleep)
    body, error = execute("task.wait", dict(task_id=made["id"], timeout_seconds=3,
                                            poll_seconds=1))
    assert not error, body
    assert body["result"]["waited"] is False
    assert body["result"]["elapsed_seconds"] <= 3   # never past the cap
    assert body["result"]["elapsed_seconds"] >= 2   # it did wait roughly the cap


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
    for arguments in (dict(task_id=made["id"], timeout_seconds=90),
                      dict(task_id=made["id"], poll_seconds=30)):
        body, error = execute("task.wait", arguments)
        assert not error, (arguments, body)   # both caps are inclusive


# --------------------------------------------------------------------------
# the transport stays alive during the wait
# --------------------------------------------------------------------------

def _serve_pair():
    """A live serve() with a queue-based stdin and an Output that records."""
    import queue
    lines = queue.Queue()

    class Input:
        def __iter__(self):
            # The reader must outlive quiet stretches: a wait of seconds sends
            # nothing for a while, and a dead reader never delivers the end.
            import queue as _queue
            while True:
                try:
                    line = lines.get(timeout=5)
                except _queue.Empty:
                    continue
                if line is None:
                    return
                yield line

    class Output(StringIO):
        def write(self, text):
            result = super().write(text)
            for message_line in text.splitlines():
                message = json.loads(message_line)
                if message.get('method') == 'elicitation/create':
                    raise AssertionError('task.wait must not ask a form')
            return result

    return lines, Input(), Output()


def wait_request(task_id: str, timeout_seconds: int = 60) -> dict:
    return dict(jsonrpc='2.0', id=7, method='tools/call', params=dict(
        name='solar_execute',
        arguments=dict(operation='task.wait',
                       arguments=dict(task_id=task_id, timeout_seconds=timeout_seconds,
                                      poll_seconds=1))))


def test_wait_does_not_deafen_the_transport(solar_env):
    """A real serve() answering a task.wait: a ping sent during the wait is
    answered before the wait ends, and a cancellation of the live request ends
    the wait at once. The task itself is never touched."""
    made = new_task()
    _activate(made["id"])
    lines, stdin, output = _serve_pair()
    server = threading.Thread(target=mcp_server.serve, args=(stdin, output), daemon=True)
    server.start()
    try:
        lines.put(json.dumps(dict(jsonrpc='2.0', id=1, method='initialize',
                                  params=dict(capabilities={'elicitation': {}}))))
        lines.put(json.dumps(wait_request(made["id"])))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:      # the wait is running
            assert server.is_alive()
            lines.put(json.dumps(dict(jsonrpc='2.0', id=2, method='ping')))
            time.sleep(0.25)
            answers = [json.loads(line) for line in output.getvalue().splitlines()]
            if any(message.get('id') == 2 for message in answers):
                break
        else:
            raise AssertionError('ping during task.wait was never answered')
        lines.put(json.dumps(dict(jsonrpc='2.0', method='notifications/cancelled',
                                  params=dict(requestId=7))))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            answers = [json.loads(line) for line in output.getvalue().splitlines()]
            if any(message.get('id') == 7 for message in answers):
                break
            time.sleep(0.05)
        else:
            raise AssertionError('cancelled task.wait never answered')
        answer = next(message for message in answers if message.get('id') == 7)
        payload = json.loads(answer['result']['content'][0]['text'])
        result = payload['result']
        assert result['cancelled_by_client'] is True
        assert result['status'] == 'active' and result['waited'] is False
    finally:
        lines.put(None)
        server.join(5)
        assert not server.is_alive()
    with solar_state.session() as store:
        assert store.task_get(made["id"])["status"] == "active"   # untouched by the wait


def test_ping_during_a_wait_is_answered_and_the_wait_still_times_out(solar_env):
    """The drain answers pings without ending the wait: after the cancelled case
    above, this pins the quiet path — the wait runs to its cap and answers."""
    made = new_task()
    _activate(made["id"])
    lines, stdin, output = _serve_pair()
    server = threading.Thread(target=mcp_server.serve, args=(stdin, output), daemon=True)
    server.start()
    try:
        lines.put(json.dumps(dict(jsonrpc='2.0', id=1, method='initialize',
                                  params=dict(capabilities={'elicitation': {}}))))
        lines.put(json.dumps(wait_request(made["id"], timeout_seconds=3)))
        lines.put(json.dumps(dict(jsonrpc='2.0', id=2, method='ping')))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            answers = [json.loads(line) for line in output.getvalue().splitlines()]
            if any(message.get('id') == 2 for message in answers):
                break
            time.sleep(0.05)
        else:
            raise AssertionError('ping during task.wait was never answered')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            answers = [json.loads(line) for line in output.getvalue().splitlines()]
            if any(message.get('id') == 7 for message in answers):
                break
            time.sleep(0.1)
        else:
            raise AssertionError('task.wait never answered')
        answer = next(message for message in answers if message.get('id') == 7)
        payload = json.loads(answer['result']['content'][0]['text'])
        result = payload['result']
        assert result['waited'] is False and result['status'] == 'active'
        assert result['elapsed_seconds'] <= 60
    finally:
        lines.put(None)
        server.join(10)
        assert not server.is_alive()


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