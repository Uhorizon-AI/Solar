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
    drafts = list((solar_env.tasks / "drafts").glob("*.md")) if (solar_env.tasks / "drafts").is_dir() else []
    assert drafts == []


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
    created = list((solar_env.tasks / "drafts").glob("*.md"))
    assert len(created) == 1
    assert "Approved task" in created[0].read_text(encoding="utf-8")

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
    drafts = list((solar_env.tasks / "drafts").glob("*.md"))
    assert len(drafts) == 1
    original = drafts[0].read_text(encoding="utf-8")
    task_id = re.search(r'^id: "?([^"\n]+)', original, re.M).group(1)
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
    assert list((solar_env.tasks / "drafts").glob("*.md")) == []
    queued = list((solar_env.tasks / "queued").glob("*.md"))
    assert len(queued) == 1
    text = queued[0].read_text(encoding="utf-8")
    assert "status: queued" in text
    assert "Do the work." in text
    assert 'title:' in text and "Ship it" in text


def test_an_already_planned_file_is_approved(solar_env):
    import re
    created = mcp_server._do_task_create({"title": "Already planned", "description": "x"})
    task_id = re.search(r"ID: (\S+)", created["output"]).group(1)
    draft = next((solar_env.tasks / "drafts").glob("*.md"))
    planned = solar_env.tasks / "planned" / draft.name
    planned.parent.mkdir(parents=True, exist_ok=True)
    planned.write_text(
        draft.read_text(encoding="utf-8").replace("status: draft", "status: planned", 1),
        encoding="utf-8")
    draft.unlink()
    result = mcp_server._do_task_approve({"task_id": task_id})
    assert result == dict(approved=True, id=task_id, from_status="planned", to_status="queued")
    assert not planned.exists()
    queued = next((solar_env.tasks / "queued").glob("*.md"))
    text = queued.read_text(encoding="utf-8")
    assert "status: queued" in text
    assert "Already planned" in text


def _cancel(solar_env, task_id: str) -> dict:
    granted = mcp_approve.grant("solar_task_cancel", {"task_id": task_id}, 900, "wire test")
    with client(solar_env) as probe:
        answer = probe.call_tool("solar_task_cancel", {
            "task_id": task_id,
            "approval_id": granted["approval_id"],
        })
    assert answer["result"]["isError"] is False, answer
    return payload(answer)["result"]


def _queued_file(solar_env) -> tuple[str, Path]:
    import re
    args = {"title": "Stop me", "queued": True}
    granted = mcp_approve.grant("solar_task_create", args, 900, "wire test")
    with client(solar_env) as probe:
        created = probe.call_tool("solar_task_create", dict(args, approval_id=granted["approval_id"]))
    assert created["result"]["isError"] is False, created
    queued = list((solar_env.tasks / "queued").glob("*.md"))
    assert len(queued) == 1
    task_id = re.search(r'^id: "?([^"\n]+)', queued[0].read_text(encoding="utf-8"), re.M).group(1)
    return task_id, queued[0]


def test_cancel_has_one_contract_on_files_and_on_sqlite(solar_env):
    """A queued task becomes cancelled, an active one stays active, in both formats."""
    import json as _json
    import solar_state

    queued_id, queued_path = _queued_file(solar_env)
    queued_files = _cancel(solar_env, queued_id)
    assert queued_files == dict(task_id=queued_id, status="cancellation_requested",
                                task_status="cancelled")
    assert not queued_path.exists()
    cancelled = solar_env.tasks / "cancelled" / queued_path.name
    assert "status: cancelled" in cancelled.read_text(encoding="utf-8")
    marker = _json.loads((solar_env.tasks / "cancellation" / f"{queued_id}.json").read_text())
    assert marker["status"] == "cancellation_requested"

    active_id, active_path = _queued_file(solar_env)
    active_dir = solar_env.tasks / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    moved = active_dir / active_path.name
    moved.write_text(active_path.read_text(encoding="utf-8").replace(
        "status: queued", "status: active", 1), encoding="utf-8")
    active_path.unlink()
    active_files = _cancel(solar_env, active_id)
    assert active_files == dict(task_id=active_id, status="cancellation_requested",
                                task_status="active")
    assert "status: active" in moved.read_text(encoding="utf-8")
    assert (solar_env.tasks / "cancellation" / f"{active_id}.json").is_file()

    with solar_state.cutover(solar_env.runtime) as cut:
        cut.upgrade_schema()
        cut.set_format("sqlite")
    with solar_state.session(solar_env.runtime, auto_backup=False) as store:
        queued_sql = store.task_create([("title", '"Q"'), ("object", '"o"')], status="queued")
        active_sql = store.task_create([("title", '"A"')], status="queued")
        store.task_transition(active_sql, "active")
    queued_base = _cancel(solar_env, queued_sql)
    active_base = _cancel(solar_env, active_sql)
    assert queued_base == dict(task_id=queued_sql, status="cancellation_requested",
                               task_status="cancelled")
    assert active_base == dict(task_id=active_sql, status="cancellation_requested",
                               task_status="active")
    assert set(queued_files) == set(queued_base) == set(active_files) == set(active_base)
    with solar_state.session(solar_env.runtime, auto_backup=False) as store:
        assert store.task_get(queued_sql)["status"] == "cancelled"
        assert store.task_get(queued_sql)["object"] == "o"
        assert store.task_get(active_sql)["status"] == "active"
        assert store.cancellation_requested(queued_sql)
        assert store.cancellation_requested(active_sql)


def test_an_unknown_format_is_refused(solar_env):
    import solar_state
    mcp_server._do_task_create({"title": "Stay a draft", "description": "x"})
    draft = next((solar_env.tasks / "drafts").glob("*.md"))
    (solar_env.runtime / "STATE_FORMAT").write_text("banana\n", encoding="utf-8")
    with pytest.raises(solar_state.StateUnavailable, match="banana"):
        mcp_server._do_task_approve({"task_id": "unused"})
    assert draft.is_file()
    assert list((solar_env.tasks / "queued").glob("*.md")) == []


def test_a_cutover_waits_for_an_mcp_file_operation(solar_env, monkeypatch):
    import re
    import solar_state
    created = mcp_server._do_task_create({"title": "Hold the lock", "description": "x"})
    task_id = re.search(r"ID: (\S+)", created["output"]).group(1)
    started, release = threading.Event(), threading.Event()
    finished: list[float] = []
    real = mcp_server._files_approve

    def slow(held_id: str) -> str:
        started.set()
        assert release.wait(30)
        result = real(held_id)
        finished.append(time.monotonic())
        return result

    monkeypatch.setattr(mcp_server, "_files_approve", slow)
    holder = threading.Thread(target=lambda: mcp_server._do_task_approve({"task_id": task_id}))
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
