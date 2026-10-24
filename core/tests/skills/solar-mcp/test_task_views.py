"""Reading tasks through solar_search: A0, closed views, no effects repeated."""
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


def read(**arguments):
    return mcp_server.call_tool("solar_search", dict(scope="tasks", **arguments))


def test_handler_loads_detail_without_repeating_effect(solar_env, recorded):
    task_id, identity, checkpoint, before, artifact = recorded
    stat, content = artifact.stat(), artifact.read_bytes()
    first, error = read(task_id=task_id)
    assert not error
    assert first["verdict"]["authority"] == "A0"
    assert first["verdict"]["code"] == "read_allowed"
    row = first["result"]
    assert row["id"] == task_id and row["status"] == "draft" and row["view"] == "detail"
    for key, value in identity.items():
        assert row[key] == value
    assert row["continuity_checkpoint"] == checkpoint
    for key in ("checkpoint", "last_verified_result", "next_check", "wait", "decision"):
        assert row["continuity_checkpoint"][key] == checkpoint[key]
        assert key not in row
    # Loading the uncertain effect neither confirms it nor executes it again.
    second, error = read(task_id=task_id)
    assert not error and second["result"] == first["result"]
    with solar_state.read_session() as store:
        assert store.task_export(task_id) == before
    assert artifact.read_bytes() == content
    assert artifact.stat().st_ino == stat.st_ino
    assert artifact.stat().st_mtime_ns == stat.st_mtime_ns


def test_listing_is_a_summary_and_never_loads_detail(solar_env, recorded, monkeypatch):
    def forbid_detail(*args):
        raise AssertionError("listing must not load detail")

    monkeypatch.setattr(solar_state.Session, "task_get", forbid_detail)
    reply, error = read()
    assert not error
    row, = reply["result"]["tasks"]
    assert row["id"] == recorded[0] and row["row_version"] >= 1
    assert "continuity_checkpoint" not in row
    assert "body" not in row


def test_unknown_task_is_an_error_not_an_empty_list(solar_env):
    reply, error = read(task_id="missing")
    assert error and reply["code"] == "task_not_found"


def test_state_filter_and_query(solar_env):
    with solar_state.session() as store:
        keep = store.task_create([("title", '"Weekly report"')], status="draft")
        store.task_create([("title", '"Other thing"')], status="draft")
    reply, error = read(query="weekly")
    assert not error and [t["id"] for t in reply["result"]["tasks"]] == [keep]
    reply, error = read(state="completed")
    assert not error and reply["result"]["tasks"] == []
    reply, error = read(state="bogus")
    assert error and reply["code"] == "invalid_arguments"


@pytest.mark.parametrize("value", ["broken json", "[]", "null", "", '""', "1", "false"])
def test_malformed_checkpoint_refuses(solar_env, value):
    with solar_state.session() as store:
        task_id = store.task_create([("continuity_checkpoint", value)])
    reply, error = read(task_id=task_id)
    assert error and "error" in reply and "result" not in reply
    assert reply["error"] == "continuity_checkpoint must be a JSON object"
    assert reply["verdict"]["authority"] == "A0"


def test_checkpoint_without_value_refuses(solar_env, monkeypatch):
    with solar_state.session() as store:
        task_id = store.task_create([("continuity_checkpoint", "unset")])
    original = solar_state.value_of
    monkeypatch.setattr(solar_state, "value_of", lambda raw:
                        None if raw is not None and raw.strip() == "unset" else original(raw))
    reply, error = read(task_id=task_id)
    assert error and "result" not in reply
    assert reply["error"] == "continuity_checkpoint must be a JSON object"


def test_every_view_reads_and_none_writes(solar_env):
    body = ("\n# Report\n\n## Steps\n\nDo it.\n\n## Result\n\nDone well.\n\n"
            "## Execution Error\n\nBoom.\n")
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"Report"'), ("scheduled_time", '"17:00"'),
                                     ("scheduled_timezone", '"Europe/Madrid"')], body)
        before = store.task_export(task_id)
    views = {view: read(task_id=task_id, view=view) for view in
             ("detail", "instructions", "config", "status", "result", "error", "history", "usage")}
    assert all(not error for _, error in views.values())
    instructions = views["instructions"][0]["result"]["instructions"]
    assert "Do it." in instructions and "Boom." not in instructions
    assert views["result"][0]["result"]["results"][0]["text"].startswith("## Result")
    assert views["error"][0]["result"]["errors"][0]["text"].startswith("## Execution Error")
    assert views["config"][0]["result"]["config"]["scheduled_timezone"] == "Europe/Madrid"
    assert views["usage"][0]["result"]["token_usage"]["attempt_count"] == 0
    assert views["history"][0]["result"]["count"] == 1
    section, error = read(task_id=task_id, view="instructions", section="Steps")
    assert not error and section["result"]["instructions"].startswith("## Steps")
    missing, error = read(task_id=task_id, view="instructions", section="Nope")
    assert error and missing["code"] == "unknown_section"
    with solar_state.read_session() as store:
        assert store.task_export(task_id) == before


def test_scope_closes_its_own_arguments(solar_env):
    for arguments in (dict(scope="tasks", task_id="x", query="y"),
                      dict(scope="tasks", view="detail"),
                      dict(scope="resources", query="x"),
                      dict(scope="capabilities")):
        reply, error = mcp_server.call_tool("solar_search", arguments)
        assert error and reply["code"] == "invalid_arguments", arguments


def test_tool_description_names_the_task_views():
    tool = mcp_server.TOOLS["solar_search"]
    description = tool["description"]
    for view in ("detail", "instructions", "config", "status", "result", "error", "history", "usage"):
        assert view in description
    assert "row_version" in description and "grants no authority" in description
    assert set(tool["inputSchema"]["properties"]) == {
        "scope", "query", "limit", "preferred_namespace", "state", "task_id", "view", "section", "uri"}
