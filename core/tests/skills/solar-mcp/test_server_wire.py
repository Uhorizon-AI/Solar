"""End to end, over the wire: a client, a pipe, and a handler that refuses.

The client here is a separate process. It cannot reach the gate except through
stdio, which is the whole point: the refusal has to survive a caller that never
read the rules.
"""
from __future__ import annotations

import json
from pathlib import Path

import mcp_approve
import mcp_probe


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
