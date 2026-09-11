"""The gate refuses on its own, in the handler, whatever the caller says."""
from __future__ import annotations

import json
import time

import mcp_gate
import mcp_server
from mcp_gate import A0, A2, A3


def registry(action_skills=None):
    reg = dict(mcp_server.TOOLS)
    reg["_action_skills"] = action_skills or {}
    return reg


def test_unknown_tool_is_refused(solar_env):
    verdict = mcp_gate.preflight("rm_minus_rf", {}, registry())
    assert not verdict.allowed
    assert verdict.code == "unknown_tool"


def test_reading_is_not_gated(solar_env):
    verdict = mcp_gate.preflight("solar_task_status", {}, registry())
    assert verdict.allowed and verdict.authority == A0


def test_mutation_without_approval_is_refused(solar_env):
    verdict = mcp_gate.preflight("solar_task_create", {"title": "X"}, registry())
    assert not verdict.allowed
    assert verdict.code == "approval_required"
    assert verdict.authority == A2


def test_a_client_cannot_invent_an_approval(solar_env):
    verdict = mcp_gate.preflight(
        "solar_task_create", {"title": "X", "approval_id": "deadbeef"}, registry())
    assert not verdict.allowed
    assert verdict.code == "approval_unknown"


def test_a_true_looking_flag_does_not_help(solar_env):
    """No caller-supplied field short-circuits the gate."""
    for forged in ({"approved": True}, {"authority": "A2"}, {"gate": "pass"},
                   {"approval_id": ""}):
        arguments = {"title": "X", **forged}
        verdict = mcp_gate.preflight("solar_task_create", arguments, registry())
        assert not verdict.allowed, forged


def test_approval_is_bound_to_the_exact_call(solar_env, monkeypatch):
    import mcp_approve
    granted = mcp_approve.grant("solar_task_create", {"title": "Uno"}, 900, "test")
    # Same approval, different arguments: refused.
    verdict = mcp_gate.preflight(
        "solar_task_create", {"title": "Otro", "approval_id": granted["approval_id"]}, registry())
    assert not verdict.allowed
    assert verdict.code == "approval_scope_mismatch"
    # The call it was granted for: allowed.
    verdict = mcp_gate.preflight(
        "solar_task_create", {"title": "Uno", "approval_id": granted["approval_id"]}, registry())
    assert verdict.allowed and verdict.code == "approval_ok"


def test_approval_expires(solar_env):
    import mcp_approve
    granted = mcp_approve.grant("solar_task_create", {"title": "Uno"}, -1, "already old")
    verdict = mcp_gate.preflight(
        "solar_task_create", {"title": "Uno", "approval_id": granted["approval_id"]}, registry())
    assert not verdict.allowed
    assert verdict.code == "approval_expired"


def test_approval_burns_on_use(solar_env):
    import mcp_approve
    granted = mcp_approve.grant("solar_task_create", {"title": "Uno"}, 900, "test")
    arguments = {"title": "Uno", "approval_id": granted["approval_id"]}
    assert mcp_gate.preflight("solar_task_create", arguments, registry()).allowed
    mcp_gate.consume("solar_task_create", arguments, registry())
    second = mcp_gate.preflight("solar_task_create", arguments, registry())
    assert not second.allowed
    assert second.code == "approval_consumed"


def test_action_needs_a_registered_skill(solar_env):
    verdict = mcp_gate.preflight(
        "solar_action_run", {"skill": "calendar-sync", "action": "run"}, registry())
    assert not verdict.allowed
    assert verdict.code == "skill_not_registered"


def test_registered_skill_still_needs_a_live_mandate(solar_env):
    reg = registry({"fixture-skill": {"actions": ["status"], "mandate": "ghost-mandate",
                                      "command": ["true"]}})
    verdict = mcp_gate.preflight(
        "solar_action_run", {"skill": "fixture-skill", "action": "status",
                             "mandate": "ghost-mandate"}, reg)
    assert not verdict.allowed
    assert verdict.code == "mandate_denied"
    assert verdict.authority == A3


def test_action_outside_the_allowed_list_is_refused(solar_env):
    reg = registry({"fixture-skill": {"actions": ["status"], "mandate": "m", "command": ["true"]}})
    verdict = mcp_gate.preflight(
        "solar_action_run", {"skill": "fixture-skill", "action": "run", "mandate": "m"}, reg)
    assert not verdict.allowed
    assert verdict.code == "action_not_allowed"


def test_live_mandate_lets_the_action_through(solar_env):
    solar_env.write_mandate("fixture-mandate", actions=("status",))
    reg = registry({"fixture-skill": {"actions": ["status"], "mandate": "fixture-mandate",
                                      "command": ["true"]}})
    verdict = mcp_gate.preflight(
        "solar_action_run", {"skill": "fixture-skill", "action": "status",
                             "mandate": "fixture-mandate"}, reg)
    assert verdict.allowed, verdict.as_dict()
    assert verdict.code == "mandate_ok"


def test_expired_mandate_is_refused(solar_env):
    solar_env.write_mandate("stale-mandate", expires="2020-01-01", actions=("status",))
    reg = registry({"fixture-skill": {"actions": ["status"], "mandate": "stale-mandate",
                                      "command": ["true"]}})
    verdict = mcp_gate.preflight(
        "solar_action_run", {"skill": "fixture-skill", "action": "status",
                             "mandate": "stale-mandate"}, reg)
    assert not verdict.allowed
    assert verdict.code == "mandate_denied"


def test_every_decision_is_recorded(solar_env):
    verdict = mcp_gate.preflight("solar_task_create", {"title": "X"}, registry())
    mcp_gate.record(verdict, {"title": "X"})
    rows = [json.loads(line) for line in
            solar_env.gate_audit.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["tool"] == "solar_task_create"
    assert rows[-1]["allowed"] is False
    assert rows[-1]["code"] == "approval_required"
