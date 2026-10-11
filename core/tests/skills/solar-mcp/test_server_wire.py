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
import operations


def client(solar_env):
    return mcp_probe.Client(env=solar_env.env, cwd=str(solar_env.workspace))


def payload(answer: dict) -> dict:
    return json.loads(answer["result"]["content"][0]["text"])


def test_an_unresolved_workspace_refuses_without_touching_a_runtime(tmp_path):
    import os
    outside = tmp_path / "outside"
    runtime = tmp_path / "runtime"
    outside.mkdir()
    env = os.environ.copy()
    env.pop("SOLAR_WORKSPACE", None)
    env["SOLAR_RUNTIME_ROOT"] = str(runtime)
    with mcp_probe.Client(env=env, cwd=str(outside)) as probe:
        read = probe.request("resources/read", dict(uri="solar://tasks"))
        called = probe.call_tool("solar_search", {"scope": "tasks"})
    assert read["error"]["code"] == -32000
    assert "workspace" in read["error"]["message"]
    assert called["result"]["isError"] is True
    assert not runtime.exists()


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
        index = next(row for row in listed if row["uri"] == "solar://index")
        assert index["name"] == "State counts"
        assert "derived" not in index["description"].lower()
        assert "stale" not in index["description"].lower()
        read = probe.request("resources/read", dict(uri="solar://tasks"))
        body = json.loads(read["result"]["contents"][0]["text"])
        assert "tasks" in body and "count" in body
        index_body = json.loads(probe.request(
            "resources/read", dict(uri="solar://index"))["result"]["contents"][0]["text"])
        assert "counts" in index_body
        assert "counters" not in index_body


def test_unknown_resource_is_an_error(solar_env):
    with client(solar_env) as probe:
        answer = probe.request("resources/read", dict(uri="solar://etc/passwd"))
        assert answer["error"]["code"] == -32602
        assert "Known:" in answer["error"]["message"]


def execute(probe, operation, arguments, **extra):
    return probe.call_tool("solar_execute", dict(operation=operation, arguments=arguments, **extra))


def approved(probe, operation, arguments):
    granted = mcp_approve.grant(operation, arguments, 900, "wire test")
    return execute(probe, operation, arguments, approval_id=granted["approval_id"])


def test_tools_are_listed(solar_env):
    with client(solar_env) as probe:
        listed = probe.request("tools/list")["result"]["tools"]
    assert [row["name"] for row in listed] == ["solar_search", "solar_docs", "solar_execute"]


def test_the_tool_schemas_are_closed(solar_env):
    with client(solar_env) as probe:
        listed = {row["name"]: row for row in probe.request("tools/list")["result"]["tools"]}
    expected = {
        "solar_search": ({"scope"}, {"scope", "query", "limit", "preferred_namespace", "state",
                                     "task_id", "view", "section", "uri"}),
        "solar_docs": ({"id"}, {"id", "revision", "reference", "section", "full"}),
        "solar_execute": ({"operation", "arguments"}, {"operation", "arguments", "approval_id"}),
    }
    for name, (required, properties) in expected.items():
        schema = listed[name]["inputSchema"]
        assert set(schema["required"]) == required
        assert set(schema["properties"]) == properties
        assert schema["additionalProperties"] is False
        for prop in schema["properties"].values():
            assert prop["type"] in ("string", "integer", "boolean", "object")
    assert set(listed["solar_execute"]["inputSchema"]["properties"]["operation"]["enum"]) == set(
        operations.OPERATIONS)
    describe = listed["solar_docs"]
    assert "section=" in describe["description"] and "full=true" in describe["description"]
    for name in ("section", "full", "reference", "revision"):
        assert describe["inputSchema"]["properties"][name]["description"]


def test_docs_refuses_combined_section_and_full_over_the_wire(solar_env):
    with client(solar_env) as probe:
        refused = probe.call_tool("solar_docs", {"id": "example:missing", "section": "Purpose", "full": True})
    message = refused["result"]["content"][0]["text"]
    assert refused["result"]["isError"] is True
    assert "cannot be combined" in message


def test_reading_needs_no_approval(solar_env):
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_search", {"scope": "tasks"})
        assert answer["result"]["isError"] is False
        assert payload(answer)["verdict"]["code"] == "read_allowed"


def test_the_handler_refuses_the_mutation(solar_env):
    """The closure of this change: refused by the handler, not by the caller."""
    with client(solar_env) as probe:
        answer = execute(probe, "task.create", {"title": "Unapproved task", "instructions": "x"})
    assert answer["result"]["isError"] is True
    refused = payload(answer)["refused"]
    assert refused["allowed"] is False
    assert refused["code"] == "approval_required"
    assert refused["gate"] == "solar-mcp/handler"
    assert refused["tool"] == "task.create"
    # And nothing was created.
    import solar_state
    with solar_state.session() as store:
        assert store.task_list() == []


def test_a_forged_approval_does_not_open_the_door(solar_env):
    with client(solar_env) as probe:
        answer = execute(probe, "task.create", {"title": "X", "instructions": "x"},
                         approval_id="0" * 16)
    assert payload(answer)["refused"]["code"] == "approval_unknown"


def test_granted_approval_lets_exactly_that_call_through_once(solar_env):
    arguments = {"title": "Approved task", "instructions": "x"}
    granted = mcp_approve.grant("task.create", arguments, 900, "wire test")
    with client(solar_env) as probe:
        first = execute(probe, "task.create", arguments, approval_id=granted["approval_id"])
        second = execute(probe, "task.create", arguments, approval_id=granted["approval_id"])

    assert first["result"]["isError"] is False, first
    assert payload(first)["verdict"]["code"] == "approval_ok"
    assert payload(first)["operation"] == "task.create"
    import solar_state
    with solar_state.session() as store:
        rows = store.task_list("draft")
    assert len(rows) == 1
    assert rows[0]["title"] == "Approved task"

    assert second["result"]["isError"] is True
    assert payload(second)["refused"]["code"] == "approval_consumed"


def test_an_action_skill_must_be_registered_first(solar_env):
    with client(solar_env) as probe:
        answer = execute(probe, "action.run", {"skill": "calendar-sync", "action": "run"})
    assert payload(answer)["refused"]["code"] == "skill_not_registered"


def test_registered_action_still_needs_a_live_mandate(solar_env):
    solar_env.register_action_skill("fixture-skill", actions=["status"],
                                    mandate="ghost", command=["true"])
    with client(solar_env) as probe:
        answer = execute(probe, "action.run",
                         {"skill": "fixture-skill", "action": "status", "mandate": "ghost"})
    assert payload(answer)["refused"]["code"] == "mandate_denied"


def test_registered_action_runs_under_a_live_mandate(solar_env):
    solar_env.write_mandate("fixture-mandate", actions=("status",))
    solar_env.register_action_skill("fixture-skill", actions=["status"],
                                    mandate="fixture-mandate", command=["echo"])
    with client(solar_env) as probe:
        answer = execute(probe, "action.run",
                         {"skill": "fixture-skill", "action": "status", "mandate": "fixture-mandate"})
    body = payload(answer)
    assert answer["result"]["isError"] is False, body
    assert body["result"]["exit_code"] == 0


def test_every_call_leaves_a_decision_in_the_gate_log(solar_env):
    with client(solar_env) as probe:
        execute(probe, "task.create", {"title": "queda registrado", "instructions": "x"})
        read = probe.request("resources/read", dict(uri="solar://gate"))
    decisions = json.loads(read["result"]["contents"][0]["text"])["decisions"]
    assert decisions[-1]["tool"] == "task.create"
    assert decisions[-1]["via"] == "solar_execute"
    assert decisions[-1]["allowed"] is False
    # The approval id never reaches the log.
    assert "approval_id" not in decisions[-1]["arguments"]


def test_create_then_approve_moves_the_same_draft_to_the_queue(solar_env):
    """The public path: task.create, then task.approve for the exact stored version."""
    with client(solar_env) as probe:
        created = approved(probe, "task.create", {"title": "Ship it", "instructions": "Do the work."})
        assert created["result"]["isError"] is False, created
        made = payload(created)["result"]
        assert made["status"] == "draft" and made["activated"] is False
        task_id = made["id"]
        import solar_state
        with solar_state.session() as store:
            assert store.task_get(task_id)["status"] == "draft"
        answer = approved(probe, "task.approve",
                          {"task_id": task_id, "expected_row_version": made["row_version"]})
    assert answer["result"]["isError"] is False, answer
    result = payload(answer)["result"]
    assert result["from_status"] == "draft"
    assert result["to_status"] == "queued"
    with solar_state.session() as store:
        task = store.task_get(task_id)
    assert task["status"] == "queued"
    assert "Do the work." in task["body"]
    assert task["title"] == "Ship it"


def test_an_already_planned_task_is_approved(solar_env):
    import solar_state
    created = operations._do_task_create({"title": "Already planned", "instructions": "x"})
    task_id = created["id"]
    with solar_state.session() as store:
        store.task_transition(task_id, "planned", expected_from="draft")
        version = store.task_get(task_id)["row_version"]
    result = operations._do_task_approve({"task_id": task_id, "expected_row_version": version})
    assert result["from_status"] == "planned" and result["to_status"] == "queued"
    with solar_state.session() as store:
        task = store.task_get(task_id)
    assert task["status"] == "queued"
    assert task["title"] == "Already planned"


def _cancel(solar_env, task_id: str) -> dict:
    import solar_state
    with solar_state.read_session() as store:
        version = store.task_get(task_id)["row_version"]
    with client(solar_env) as probe:
        answer = approved(probe, "task.cancel", {"task_id": task_id, "expected_row_version": version})
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
    with client(solar_env) as probe:
        refused = approved(probe, "task.cancel", {"task_id": queued_id, "expected_row_version": 1})
    assert refused["result"]["isError"] is True
    (solar_env.runtime / "STATE_FORMAT").write_text("sqlite\n", encoding="utf-8")


def test_an_unknown_format_is_refused(solar_env):
    import solar_state
    created = operations._do_task_create({"title": "Stay a draft", "instructions": "x"})
    task_id = created["id"]
    (solar_env.runtime / "STATE_FORMAT").write_text("banana\n", encoding="utf-8")
    with pytest.raises(solar_state.StateUnavailable, match="banana"):
        operations._do_task_approve({"task_id": task_id, "expected_row_version": created["row_version"]})
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
        probe.call_tool("solar_search", {"scope": "tasks"})
        execute(probe, "task.create", {"title": "X", "instructions": "x"})

    for path in (solar_env.gate_audit, solar_env.runtime):
        assert str(path).startswith(str(solar_env.tmp_path))
    assert solar_env.gate_audit.exists(), "the fixture audit was never written"
    for path, mark in before:
        assert _fingerprint(path) == mark, f"the live gate store was written: {path}"
