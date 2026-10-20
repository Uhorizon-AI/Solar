"""solar_search and solar_docs: bounded, authorized reading across skills, documents and contracts."""
from __future__ import annotations

import json

import pytest

import mcp_server
import operations
from mcp_helpers import call, docs, search


def test_search_operations_lists_every_operation_with_its_authority(solar_env):
    found = search(scope="operations")
    rows = {row["name"]: row for row in found["operations"]}
    assert set(rows) == set(operations.OPERATIONS)
    assert rows["telegram.send"]["external_communication"] is True
    assert rows["action.run"]["authority"] == "A3"
    assert all(rows[n]["authority"] == "A2" for n in rows
               if n.startswith("task.") and n != "task.wait")
    assert rows["task.wait"]["authority"] == "A0"
    assert [r["name"] for r in search(scope="operations", query="archive")["operations"]] == ["task.archive"]


def test_an_operation_contract_is_readable_before_it_is_called(solar_env):
    contract = docs(id="operation:task.approve")
    assert contract["authority"] == "A2" and contract["arguments"]["additionalProperties"] is False
    assert set(contract["arguments"]["required"]) == {"task_id", "expected_row_version"}
    assert "approval_scope_mismatch" in contract["errors"] and "task_changed" in contract["errors"]
    assert contract["mandate"].startswith("Refused")
    assert docs(id="operation:telegram.send")["external_communication"] is True
    for bad in ({"section": "x"}, {"full": True}, {"revision": "x"}):
        body, error = call("solar_docs", dict(id="operation:task.approve", **bad))
        assert error
    body, error = call("solar_docs", dict(id="operation:task.delete"))
    assert error and body["code"] == "unknown_operation" and "task.create" in body["error"]


def test_core_documents_are_listed_and_read_by_section(solar_env):
    found = search(scope="docs", query="authority")
    ids = [row["id"] for row in found["results"]]
    assert "core-doc:authority-model" in ids
    entry = next(r for r in found["results"] if r["id"] == "core-doc:authority-model")
    outline = docs(id=entry["id"], revision=entry["revision"])
    assert outline["type"] == "document" and outline["outline"] is True and outline["sections"]
    title = outline["sections"][0]["title"]
    part = docs(id=entry["id"], section=title)
    assert part["section"] == title and part["instructions"].startswith("#")
    assert len(json.dumps(part)) < len(json.dumps(docs(id=entry["id"], full=True)))


def test_core_documents_are_closed_to_paths_and_stale_revisions(solar_env):
    for bad in ("core-doc:../AGENTS", "core-doc:../../CLAUDE", "core-doc:/etc/passwd",
                "core-doc:authority-model.md", "core-doc:", "core-doc:missing"):
        body, error = call("solar_docs", dict(id=bad))
        assert error and body["code"] == "docs_refused", bad
    body, error = call("solar_docs", dict(id="core-doc:authority-model", revision="0" * 64))
    assert error and "revision" in body["error"]
    body, error = call("solar_docs", dict(id="core-doc:authority-model", reference="x.md"))
    assert error


def test_only_regular_markdown_directly_under_core_docs_is_a_document(solar_env, tmp_path, monkeypatch):
    import docs_registry
    root = tmp_path / "install" / "core" / "docs"
    root.mkdir(parents=True)
    (root / "ok.md").write_text("# Okay\n\nbody\n")
    (root / "notes.txt").write_text("no")
    (root / "Bad_Name.md").write_text("no")
    secret = tmp_path / "secret.md"
    secret.write_text("# secret\n")
    (root / "link.md").symlink_to(secret)
    (root / "sub").mkdir()
    (root / "sub" / "deep.md").write_text("# deep\n")
    monkeypatch.setattr(docs_registry, "_docs_root", lambda: root)
    assert list(docs_registry.core_docs()) == ["core-doc:ok"]


def test_skills_are_still_found_and_described(solar_env):
    folder = solar_env.workspace / "planets/example/skills/demo"
    folder.mkdir(parents=True)
    (folder / "references").mkdir()
    (folder / "SKILL.md").write_text("---\nname: demo\ndescription: fixture capability\n---\n\nComplete instructions.\n")
    (folder / "references/detail.md").write_text("Detailed fixture")
    found = search(scope="capabilities", query="example:demo")["results"][0]
    assert found["id"] == "example:demo" and found["type"] == "instruction"
    described = docs(id=found["id"], revision=found["revision"])
    assert "Complete instructions" in described["instructions"]
    assert docs(id=found["id"], reference="references/detail.md")["instructions"] == "Detailed fixture"
    # An instruction skill is documentation only: it never shows up as something to execute.
    assert "example:demo" not in {r["name"] for r in search(scope="operations")["operations"]}


def test_resources_stay_readable_through_search_and_through_the_protocol(solar_env):
    listed = search(scope="resources")["resources"]
    assert {r["uri"] for r in listed} == set(mcp_server.READERS)
    read = search(scope="resources", uri="solar://index")
    assert read["uri"] == "solar://index" and "counts" in read["contents"]
    body, error = call("solar_search", dict(scope="resources", uri="solar://etc/passwd"))
    assert error and body["code"] == "unknown_resource" and "solar://health" in body["error"]
    response = mcp_server.handle(dict(jsonrpc="2.0", id=1, method="resources/read", params=dict(uri="solar://tasks")))
    assert "tasks" in json.loads(response["result"]["contents"][0]["text"])


def test_tool_descriptions_point_readers_to_the_cheap_path():
    description = mcp_server.TOOLS["solar_docs"]["description"]
    assert 'section="<exact title>"' in description and "full=true" in description
    assert "operation:<name>" in description and "core-doc:<name>" in description
    assert "task.approve" in mcp_server.TOOLS["solar_execute"]["description"]
    assert "never queues" in mcp_server.TOOLS["solar_execute"]["description"]
