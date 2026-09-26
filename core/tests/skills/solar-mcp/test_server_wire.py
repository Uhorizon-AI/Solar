"""End to end, over the wire: a client, a pipe, and a handler that refuses.

The client here is a separate process. It cannot reach the gate except through
stdio, which is the whole point: the refusal has to survive a caller that never
read the rules.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import mcp_approve
import mcp_probe
import mcp_server


def client(solar_env):
    return mcp_probe.Client(env=solar_env.env, cwd=str(solar_env.workspace))


def payload(answer: dict) -> dict:
    return json.loads(answer["result"]["content"][0]["text"])


def test_initialize_announces_the_server(solar_env):
    with client(solar_env) as probe:
        answer = probe.request("ping")
        assert answer["result"] == {}


def test_unknown_resource_names_the_catalog(solar_env):
    with client(solar_env) as probe:
        answer = probe.request("resources/read", dict(uri="solar://status"))
        assert answer["error"]["code"] == -32602
        assert "solar://health" in answer["error"]["message"]
        assert "solar://status" in answer["error"]["message"]


def test_resources_are_open(solar_env):
    with client(solar_env) as probe:
        listed = probe.request("resources/list")["result"]["resources"]
        assert {row["uri"] for row in listed} >= {
            "solar://health", "solar://tasks", "solar://index",
            "solar://delegations", "solar://gate"}
        read = probe.request("resources/read", dict(uri="solar://tasks"))
        body = json.loads(read["result"]["contents"][0]["text"])
        assert "tasks" in body and "count" in body


def test_unknown_resource_is_an_error(solar_env):
    with client(solar_env) as probe:
        answer = probe.request("resources/read", dict(uri="solar://etc/passwd"))
        assert answer["error"]["code"] == -32602
        assert "Known:" in answer["error"]["message"]


def test_tools_are_listed(solar_env):
    with client(solar_env) as probe:
        names = {row["name"] for row in probe.request("tools/list")["result"]["tools"]}
        assert names == {"solar_task_status", "solar_task_create",
                         "solar_task_approve", "solar_task_cancel", "solar_task_requeue",
                         "solar_telegram_send", "solar_action_run"}


def test_reading_a_verb_needs_no_approval(solar_env):
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_task_status", {})
        assert answer["result"]["isError"] is False
        assert payload(answer)["verdict"]["code"] == "read_allowed"


def test_the_handler_refuses_the_mutation(solar_env):
    """The closure of this change: refused by the handler, not by the caller."""
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_task_create", {"title": "Unapproved task"})
    assert answer["result"]["isError"] is True
    refused = payload(answer)["refused"]
    assert refused["allowed"] is False
    assert refused["code"] == "approval_required"
    assert refused["gate"] == "solar-mcp/handler"
    # And nothing was created.
    import solar_state
    with solar_state.session() as store:
        assert store.task_list() == []


def test_a_forged_approval_does_not_open_the_door(solar_env):
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_task_create",
                                 {"title": "X", "approval_id": "0" * 16})
    assert payload(answer)["refused"]["code"] == "approval_unknown"


def test_granted_approval_lets_exactly_that_call_through_once(solar_env):
    granted = mcp_approve.grant("solar_task_create", {"title": "Approved task"}, 900, "wire test")
    arguments = {"title": "Approved task", "approval_id": granted["approval_id"]}
    with client(solar_env) as probe:
        first = probe.call_tool("solar_task_create", arguments)
        second = probe.call_tool("solar_task_create", arguments)

    assert first["result"]["isError"] is False, first
    assert payload(first)["verdict"]["code"] == "approval_ok"
    import solar_state
    with solar_state.session() as store:
        rows = store.task_list("draft")
    assert len(rows) == 1
    assert rows[0]["title"] == "Approved task"

    assert second["result"]["isError"] is True
    assert payload(second)["refused"]["code"] == "approval_consumed"


def test_an_action_skill_must_be_registered_first(solar_env):
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_action_run",
                                 {"skill": "calendar-sync", "action": "run"})
    assert payload(answer)["refused"]["code"] == "skill_not_registered"


def test_registered_action_still_needs_a_live_mandate(solar_env):
    solar_env.register_action_skill("fixture-skill", actions=["status"],
                                    mandate="ghost", command=["true"])
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_action_run",
                                 {"skill": "fixture-skill", "action": "status", "mandate": "ghost"})
    assert payload(answer)["refused"]["code"] == "mandate_denied"


def test_registered_action_runs_under_a_live_mandate(solar_env):
    solar_env.write_mandate("fixture-mandate", actions=("status",))
    solar_env.register_action_skill("fixture-skill", actions=["status"],
                                    mandate="fixture-mandate", command=["echo"])
    with client(solar_env) as probe:
        answer = probe.call_tool(
            "solar_action_run",
            {"skill": "fixture-skill", "action": "status", "mandate": "fixture-mandate"})
    body = payload(answer)
    assert answer["result"]["isError"] is False, body
    assert body["result"]["exit_code"] == 0


def test_every_call_leaves_a_decision_in_the_gate_log(solar_env):
    with client(solar_env) as probe:
        probe.call_tool("solar_task_create", {"title": "queda registrado"})
        read = probe.request("resources/read", dict(uri="solar://gate"))
    decisions = json.loads(read["result"]["contents"][0]["text"])["decisions"]
    assert decisions[-1]["tool"] == "solar_task_create"
    assert decisions[-1]["allowed"] is False
    # The approval id never reaches the log.
    assert "approval_id" not in decisions[-1]["arguments"]


def test_create_then_approve_moves_the_same_draft_to_the_queue(solar_env):
    """The public path: solar_task_create, then solar_task_approve. No plan step."""
    import re
    granted = mcp_approve.grant(
        "solar_task_create",
        {"title": "Ship it", "description": "Do the work."},
        900, "wire test")
    with client(solar_env) as probe:
        created = probe.call_tool("solar_task_create", {
            "title": "Ship it",
            "description": "Do the work.",
            "approval_id": granted["approval_id"],
        })
    assert created["result"]["isError"] is False, created
    task_id = payload(created)["result"]["id"]
    approved = mcp_approve.grant("solar_task_approve", {"task_id": task_id}, 900, "wire test")
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_task_approve", {
            "task_id": task_id,
            "approval_id": approved["approval_id"],
        })
    assert answer["result"]["isError"] is False, answer
    result = payload(answer)["result"]
    assert result["from_status"] == "draft"
    assert result["to_status"] == "queued"
    import solar_state
    with solar_state.session() as store:
        task = store.task_get(task_id)
    assert task["status"] == "queued"
    assert "Do the work." in task["body"]
    assert task["title"] == "Ship it"


def test_an_already_planned_task_is_approved(solar_env):
    import solar_state
    created = mcp_server._do_task_create({"title": "Already planned", "description": "x"})
    task_id = created["id"]
    with solar_state.session() as store:
        store.task_transition(task_id, "planned", expected_from="draft")
    result = mcp_server._do_task_approve({"task_id": task_id})
    assert result == dict(approved=True, id=task_id, from_status="planned", to_status="queued")
    with solar_state.session() as store:
        task = store.task_get(task_id)
    assert task["status"] == "queued"
    assert task["title"] == "Already planned"


def _cancel(solar_env, task_id: str) -> dict:
    granted = mcp_approve.grant("solar_task_cancel", {"task_id": task_id}, 900, "wire test")
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_task_cancel", {
            "task_id": task_id,
            "approval_id": granted["approval_id"],
        })
    assert answer["result"]["isError"] is False, answer
    return payload(answer)["result"]


def test_cancel_is_the_row_and_files_are_refused(solar_env):
    """A queued task becomes cancelled. An active one stays active. Files refuse."""
    import solar_state

    with solar_state.session() as store:
        queued_id = store.task_create([("title", '"Q"'), ("object", '"o"')], "\n# Q\n", status="queued")
        active_id = store.task_create([("title", '"A"')], "\n# A\n", status="queued")
        store.task_transition(active_id, "active", expected_from="queued")
    queued = _cancel(solar_env, queued_id)
    active = _cancel(solar_env, active_id)
    assert queued == dict(task_id=queued_id, status="cancellation_requested",
                          task_status="cancelled")
    assert active == dict(task_id=active_id, status="cancellation_requested",
                          task_status="active")
    with solar_state.session() as store:
        assert store.task_get(queued_id)["status"] == "cancelled"
        assert store.task_get(queued_id)["object"] == "o"
        assert store.task_get(active_id)["status"] == "active"
        assert store.cancellation_requested(queued_id)
        assert store.cancellation_requested(active_id)

    (solar_env.runtime / "STATE_FORMAT").write_text("files\n", encoding="utf-8")
    granted = mcp_approve.grant("solar_task_cancel", {"task_id": queued_id}, 900, "wire test")
    with client(solar_env) as probe:
        refused = probe.call_tool("solar_task_cancel", {
            "task_id": queued_id, "approval_id": granted["approval_id"],
        })
    assert refused["result"]["isError"] is True
    (solar_env.runtime / "STATE_FORMAT").write_text("sqlite\n", encoding="utf-8")


def test_an_unknown_format_is_refused(solar_env):
    import solar_state
    created = mcp_server._do_task_create({"title": "Stay a draft", "description": "x"})
    task_id = created["id"]
    (solar_env.runtime / "STATE_FORMAT").write_text("banana\n", encoding="utf-8")
    with pytest.raises(solar_state.StateUnavailable, match="banana"):
        mcp_server._do_task_approve({"task_id": task_id})
    (solar_env.runtime / "STATE_FORMAT").write_text("sqlite\n", encoding="utf-8")
    with solar_state.session() as store:
        assert store.task_get(task_id)["status"] == "draft"


def test_a_cutover_waits_while_a_session_holds_the_lock(solar_env):
    import solar_state
    started, release = threading.Event(), threading.Event()
    finished: list[float] = []

    def hold() -> None:
        with solar_state.session() as store:
            started.set()
            assert release.wait(30)
            store.task_create([("title", '"Hold"')], "\n# Hold\n", status="draft")
            finished.append(time.monotonic())

    holder = threading.Thread(target=hold)
    holder.start()
    assert started.wait(30)
    acquired: list[float] = []

    def take() -> None:
        with solar_state.cutover(timeout=30):
            acquired.append(time.monotonic())

    cutter = threading.Thread(target=take)
    cutter.start()
    time.sleep(0.4)
    assert acquired == []
    release.set()
    holder.join(30)
    cutter.join(30)
    assert finished and acquired and finished[0] <= acquired[0]


def _fingerprint(path: Path):
    """Size and mtime, or None when the path is not there."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def test_nothing_was_written_outside_the_fixture(solar_env):
    """The suite writes in the fixture and the live store does not move.

    Not "the live store does not exist": Louis exercises this server against the
    cable on purpose, so its audit is expected to hold real decisions. What must
    never happen is a test adding one.
    """
    live = Path.home() / "Library" / "Application Support" / "Solar" / "runtime" / "mcp"
    before = [(path, _fingerprint(path))
              for path in (live, live / "audit.jsonl", live / "approvals")]

    with client(solar_env) as probe:
        probe.call_tool("solar_task_status", {})
        probe.call_tool("solar_task_create", {"title": "X"})

    for path in (solar_env.gate_audit, solar_env.runtime):
        assert str(path).startswith(str(solar_env.tmp_path))
    assert solar_env.gate_audit.exists(), "the fixture audit was never written"
    for path, mark in before:
        assert _fingerprint(path) == mark, f"the live gate store was written: {path}"
