"""Read recorded continuity through the A0 handler without repeating effects."""
import json

import pytest

import mcp_server
import solar_state


@pytest.fixture
def recorded(solar_env):
    artifact = solar_env.workspace / "result.md"
    artifact.write_text("One existing local effect.\n")
    checkpoint = {
        "checkpoint": {"state": "effect_uncertain", "artifact_ref": "result.md",
                       "retry": "blocked_until_loaded_and_verified"},
        "last_verified_result": {"path": "previous.md", "sha256": "a" * 64,
                                 "verified_at": "2026-10-09T00:00:00+00:00"},
        "next_check": {"at": "2026-10-13", "action": "Review response",
                       "source": "lead.md#next-step"},
        "wait": "Await response or owner review",
        "decision": {"status": "pending", "owner": "owner", "source": "contract.md",
                     "valid_from": "2026-10-09", "valid_until": "2026-10-13"},
    }
    settings = json.loads((solar_env.workspace / ".solar/settings.json").read_text())
    identity = {"workspace_id": settings["workspace_id"], "agent": "fixture-sales",
                "planet": "fixture", "responsibility": "sales-follow-up",
                "agent_contract": "contract.md"}
    with solar_state.session() as store:
        task_id = store.task_create(
            [("title", "Continuity proof"),
             *[(k, json.dumps(v)) for k, v in identity.items()],
             ("continuity_checkpoint", json.dumps(checkpoint))],
            task_id="continuity-proof", body="Fixture, never queued.\n")
        before = store.task_export(task_id)
    return task_id, identity, checkpoint, before, artifact


def test_handler_loads_detail_without_repeating_effect(solar_env, recorded):
    task_id, identity, checkpoint, before, artifact = recorded
    stat, content = artifact.stat(), artifact.read_bytes()
    first, error = mcp_server.call_tool("solar_task_status", {"task_id": task_id})
    assert not error
    assert first["verdict"]["authority"] == "A0"
    assert first["verdict"]["code"] == "read_allowed"
    row, = first["result"]["tasks"]
    assert row["id"] == task_id and row["state"] == "drafts"
    for key, value in identity.items():
        assert row[key] == value
    assert row["continuity_checkpoint"] == checkpoint
    for key in ("checkpoint", "last_verified_result", "next_check", "wait", "decision"):
        assert row["continuity_checkpoint"][key] == checkpoint[key]
        assert key not in row
    # Loading the uncertain effect neither confirms it nor executes it again.
    second, error = mcp_server.call_tool("solar_task_status", {"task_id": task_id})
    assert not error and second["result"] == first["result"]
    with solar_state.read_session() as store:
        assert store.task_export(task_id) == before
    assert artifact.read_bytes() == content
    assert artifact.stat().st_ino == stat.st_ino
    assert artifact.stat().st_mtime_ns == stat.st_mtime_ns


def test_queue_listing_keeps_summary_only(solar_env, recorded, monkeypatch):
    expected = mcp_server._read_tasks()["tasks"]

    def forbid_detail(*args):
        raise AssertionError("queue listing must not load detail")

    monkeypatch.setattr(solar_state.Session, "task_get", forbid_detail)
    reply, error = mcp_server.call_tool("solar_task_status", {})
    assert not error
    assert reply["result"] == {"count": len(expected), "tasks": expected}
    assert "continuity_checkpoint" not in reply["result"]["tasks"][0]


def test_ordinary_missing_and_filtered_task(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([("title", "Ordinary task")])
    expected = mcp_server._read_tasks()["tasks"]
    reply, error = mcp_server.call_tool("solar_task_status", {"task_id": task_id})
    assert not error and reply["result"]["tasks"] == expected
    for arguments in ({"task_id": "missing"}, {"task_id": task_id, "state": "completed"}):
        missing, error = mcp_server.call_tool("solar_task_status", arguments)
        assert not error and missing["result"] == {"count": 0, "tasks": []}


@pytest.mark.parametrize("value", ["broken json", "[]", "null", "", '""', "1", "false"])
def test_malformed_checkpoint_refuses(solar_env, value):
    with solar_state.session() as store:
        task_id = store.task_create([("continuity_checkpoint", value)])
    reply, error = mcp_server.call_tool("solar_task_status", {"task_id": task_id})
    assert error and "error" in reply and "result" not in reply
    assert reply["error"] == "continuity_checkpoint must be a JSON object"
    assert reply["verdict"]["authority"] == "A0"


def test_checkpoint_without_value_refuses(solar_env, monkeypatch):
    with solar_state.session() as store:
        task_id = store.task_create([("continuity_checkpoint", "unset")])
    original = solar_state.value_of
    monkeypatch.setattr(solar_state, "value_of", lambda raw:
                        None if raw is not None and raw.strip() == "unset" else original(raw))
    reply, error = mcp_server.call_tool("solar_task_status", {"task_id": task_id})
    assert error and "result" not in reply
    assert reply["error"] == "continuity_checkpoint must be a JSON object"
    assert reply["verdict"]["authority"] == "A0"


def test_task_disappearing_during_detail_read_refuses(solar_env, recorded, monkeypatch):
    task_id = recorded[0]
    monkeypatch.setattr(solar_state.Session, "task_get", lambda *args: None)
    reply, error = mcp_server.call_tool("solar_task_status", {"task_id": task_id})
    assert error and "result" not in reply
    assert reply["error"] == "task disappeared while reading its detail"
    assert reply["verdict"]["authority"] == "A0"


def test_tool_description_matches_nested_read_contract():
    tool = mcp_server.TOOLS["solar_task_status"]
    description = tool["description"]
    assert tool["authority"] == "A0"
    assert "unchanged queue summary" in description
    assert "continuity_checkpoint" in description and "inside that object" in description
    assert "Refuses if the stored checkpoint is not a JSON object" in description
    assert "does not authorize a retry" in description
    assert "continuity_checkpoint" in tool["inputSchema"]["properties"]["task_id"]["description"]
    assert set(tool["inputSchema"]["properties"]) == {"task_id", "state"}
