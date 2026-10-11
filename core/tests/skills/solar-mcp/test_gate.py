"""The gate decides per operation. No approval, no mandate, no exception."""
import json

import mcp_approve
import mcp_gate
import mcp_server
import operations


def registry(action_skills=None, **overrides):
    reg = {name: op.gate_spec() for name, op in operations.OPERATIONS.items()}
    reg.update(overrides)
    reg["_action_skills"] = action_skills or {}
    return reg


def test_unknown_operation_is_refused(solar_env):
    verdict = mcp_gate.preflight("task.delete", {}, registry())
    assert not verdict.allowed
    assert verdict.code == "unknown_tool"


def test_reading_is_not_gated(solar_env):
    verdict = mcp_gate.preflight("solar_search", {"scope": "tasks"}, {"solar_search": mcp_server.READ_SPEC})
    assert verdict.allowed
    assert verdict.code == "read_allowed"


def test_approve_under_a_mandate_is_refused(solar_env):
    verdict = mcp_gate.preflight("task.approve", {"task_id": "t1", "mandate": "nightly"}, registry())
    assert not verdict.allowed
    assert verdict.code == "a3_refused"


def test_every_task_mutation_needs_approval(solar_env):
    for name in ("task.create", "task.update", "task.schedule", "task.approve",
                 "task.cancel", "task.requeue", "task.archive"):
        verdict = mcp_gate.preflight(name, {"task_id": "t1"}, registry())
        assert not verdict.allowed, name
        assert verdict.code == "approval_required", name


def test_a_client_cannot_invent_an_approval(solar_env):
    verdict = mcp_gate.preflight("task.create", {"title": "X", "approval_id": "deadbeef"}, registry())
    assert verdict.code == "approval_unknown"


def test_a_true_looking_flag_does_not_help(solar_env):
    for forged in ({"approved": True}, {"approval": "yes"}, {"authority": "A2"}, {"force": 1}):
        verdict = mcp_gate.preflight("task.create", {"title": "X", **forged}, registry())
        assert not verdict.allowed


def test_approval_is_bound_to_the_exact_call(solar_env, monkeypatch):
    granted = mcp_approve.grant("task.create", {"title": "One", "instructions": "a"}, 900, "test")
    other = mcp_gate.preflight(
        "task.create", {"title": "Other", "instructions": "a", "approval_id": granted["approval_id"]}, registry())
    assert other.code == "approval_scope_mismatch"
    same = mcp_gate.preflight(
        "task.create", {"title": "One", "instructions": "a", "approval_id": granted["approval_id"]}, registry())
    assert same.allowed


def test_approval_expires(solar_env):
    granted = mcp_approve.grant("task.create", {"title": "One"}, -1, "already old")
    verdict = mcp_gate.preflight(
        "task.create", {"title": "One", "approval_id": granted["approval_id"]}, registry())
    assert verdict.code == "approval_expired"


def test_approval_burns_on_use(solar_env):
    granted = mcp_approve.grant("task.create", {"title": "One"}, 900, "test")
    arguments = {"title": "One", "approval_id": granted["approval_id"]}
    assert mcp_gate.preflight("task.create", arguments, registry()).allowed
    mcp_gate.consume("task.create", arguments, registry())
    assert mcp_gate.preflight("task.create", arguments, registry()).code == "approval_consumed"


def test_action_needs_a_registered_skill(solar_env):
    verdict = mcp_gate.preflight("action.run", {"skill": "calendar-sync", "action": "run"}, registry())
    assert verdict.code == "skill_not_registered"


def test_registered_skill_still_needs_a_live_mandate(solar_env):
    reg = registry({"fixture-skill": dict(actions=["status"], mandate="ghost", command=["true"])})
    verdict = mcp_gate.preflight(
        "action.run", {"skill": "fixture-skill", "action": "status", "mandate": "ghost"}, reg)
    assert verdict.code == "mandate_denied"


def test_action_outside_the_allowed_list_is_refused(solar_env):
    reg = registry({"fixture-skill": dict(actions=["status"], mandate="m", command=["true"])})
    verdict = mcp_gate.preflight(
        "action.run", {"skill": "fixture-skill", "action": "run", "mandate": "m"}, reg)
    assert verdict.code == "action_not_allowed"


def test_live_mandate_lets_the_action_through(solar_env):
    solar_env.write_mandate("fixture-mandate", actions=("status",))
    reg = registry({"fixture-skill": dict(actions=["status"], mandate="fixture-mandate", command=["true"])})
    verdict = mcp_gate.preflight(
        "action.run", {"skill": "fixture-skill", "action": "status", "mandate": "fixture-mandate"}, reg)
    assert verdict.allowed
    assert verdict.code == "mandate_ok"


def test_a_caller_cannot_swap_the_registered_mandate(solar_env):
    """A live mandate for another purpose must not unlock this skill."""
    solar_env.write_mandate("fixture-mandate", actions=("status",))
    solar_env.write_mandate("other-mandate", actions=("status",))
    reg = registry({"fixture-skill": dict(actions=["status"], mandate="fixture-mandate", command=["true"])})
    verdict = mcp_gate.preflight(
        "action.run", {"skill": "fixture-skill", "action": "status", "mandate": "other-mandate"}, reg)
    assert not verdict.allowed
    assert verdict.code == "mandate_mismatch"


def test_expired_mandate_is_refused(solar_env):
    solar_env.write_mandate("old-mandate", expires="2020-01-01", actions=("status",))
    reg = registry({"fixture-skill": dict(actions=["status"], mandate="old-mandate", command=["true"])})
    verdict = mcp_gate.preflight(
        "action.run", {"skill": "fixture-skill", "action": "status", "mandate": "old-mandate"}, reg)
    assert verdict.code == "mandate_denied"


def test_every_decision_is_recorded_with_its_outcome(solar_env):
    body, error = mcp_server.call_tool(
        "solar_execute", dict(operation="task.create", arguments=dict(title="X", instructions="y")))
    assert error
    rows = [json.loads(line) for line in solar_env.gate_audit.read_text().splitlines()]
    last = rows[-1]
    assert last["kind"] == "decision" and last["tool"] == "task.create"
    assert last["via"] == "solar_execute" and last["allowed"] is False
    assert last["trace_id"] == body["trace_id"]
    assert "approval_id" not in last["arguments"]


def test_an_allowed_call_leaves_decision_and_outcome_under_one_trace(solar_env):
    from mcp_helpers import execute
    body, error = execute("task.create", dict(title="Traced", instructions="y"))
    assert not error
    rows = [json.loads(line) for line in solar_env.gate_audit.read_text().splitlines()]
    mine = [r for r in rows if r.get("trace_id") == body["trace_id"]]
    assert [r["kind"] for r in mine] == ["decision", "outcome"]
    assert mine[1]["ok"] is True and mine[1]["tool"] == "task.create"
