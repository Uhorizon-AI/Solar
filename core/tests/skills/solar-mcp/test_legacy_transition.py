"""Clients that still call the previous names get a loud, non-executing answer."""
from __future__ import annotations

import json

import pytest

import mcp_probe
import mcp_server
import solar_state
from mcp_helpers import call, docs, payload

ARGUMENTS = {
    "solar_capability_search": {"query": "x"},
    "solar_capability_describe": {"id": "x"},
    "solar_task_status": {},
    "solar_task_create": {"title": "Created by an old client"},
    "solar_task_approve": {"task_id": "t"},
    "solar_task_cancel": {"task_id": "t"},
    "solar_task_requeue": {"task_id": "t"},
    "solar_telegram_send": {"text": "hello", "chat_id": "1"},
    "solar_action_run": {"skill": "s", "action": "a"},
}


def test_every_previous_name_has_a_declared_replacement():
    assert set(mcp_server.LEGACY_TOOLS) == set(ARGUMENTS)
    for old, (tool, template) in mcp_server.LEGACY_TOOLS.items():
        assert tool in mcp_server.TOOLS and old not in mcp_server.TOOLS
        if tool == "solar_execute":
            assert template["operation"] in mcp_server.operations.OPERATIONS


@pytest.mark.parametrize("old", sorted(ARGUMENTS))
def test_an_old_name_is_refused_loudly_and_executes_nothing(solar_env, old):
    body, error = call(old, ARGUMENTS[old])
    assert error is True
    assert body["code"] == "tool_renamed" and body["executed"] is False and "result" not in body
    assert body["replacement"]["tool"] in mcp_server.TOOLS
    assert body["legacy_tool"] == old and old in body["error"]
    assert body["migration"] == {"tool": "solar_docs", "arguments": {"id": mcp_server.MIGRATION_DOC}}
    with solar_state.session() as store:
        assert store.task_list() == []
    rows = [json.loads(line) for line in solar_env.gate_audit.read_text().splitlines()]
    last = rows[-1]
    assert last["tool"] == old and last["allowed"] is False and last["code"] == "tool_renamed"


def test_the_migration_reference_is_readable_through_solar_docs(solar_env):
    # Resolves against the real repository docs when the fixture install is the checkout.
    text = docs(id=mcp_server.MIGRATION_DOC, full=True)["instructions"]
    for old in ARGUMENTS:
        assert old in text


def test_the_old_names_are_not_a_second_public_catalog(solar_env):
    with mcp_probe.Client(env=solar_env.env, cwd=str(solar_env.workspace)) as probe:
        names = [t["name"] for t in probe.request("tools/list")["result"]["tools"]]
        answer = probe.call_tool("solar_task_status", {})
    assert names == ["solar_search", "solar_docs", "solar_execute"]
    assert answer["result"]["isError"] is True
    assert payload(answer)["code"] == "tool_renamed"


def test_unknown_names_are_still_plainly_unknown(solar_env):
    body, error = call("solar_made_up", {})
    assert error and body["refused"]["code"] == "unknown_tool" and "code" not in body
