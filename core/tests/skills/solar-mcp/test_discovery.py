"""Discovery contracts through the real stdio server."""
import json
from pathlib import Path
import pytest
import capability_registry as registry
import mcp_probe


def fixture_skill(env, name="demo", text="fixture capability"):
    folder = env.workspace / "planets/example/skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: " + name + "\ndescription: " + text + "\n---\n\nComplete instructions.\n")
    return folder


def body(answer):
    return json.loads(answer["result"]["content"][0]["text"])


def test_search_describe_and_registered_reference_over_wire(solar_env):
    folder = fixture_skill(solar_env)
    (folder / "references").mkdir()
    (folder / "references/detail.md").write_text("Detailed fixture")
    with mcp_probe.Client(env=solar_env.env, cwd=str(solar_env.workspace)) as client:
        found = body(client.call_tool("solar_capability_search", {"query": "example:demo"}))["result"]
        assert len(json.dumps(found).encode()) < 8192
        entry = found["results"][0]
        assert entry["id"] == "example:demo"
        assert "path" not in entry
        args = dict(id=entry["id"], revision=entry["revision"])
        described = body(client.call_tool("solar_capability_describe", args))["result"]
        assert "Complete instructions" in described["instructions"]
        ref = body(client.call_tool("solar_capability_describe", dict(args, reference="references/detail.md")))["result"]
        assert ref["instructions"] == "Detailed fixture"
        invalid = client.call_tool("solar_capability_describe", dict(args, reference="../../secret.md"))
        assert invalid["result"]["isError"]


def test_exclusions_stale_revision_and_symlink_escape(solar_env):
    folder = fixture_skill(solar_env)
    found = registry.search("example:demo")["results"][0]
    (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text() + "Changed")
    with pytest.raises(ValueError, match="revision"):
        registry.describe("example:demo", found["revision"])
    (solar_env.workspace / ".solar/settings.json").write_text(json.dumps({"sync_exclude_skills": ["example:demo"]}))
    assert not registry.search("example:demo")["results"]
    with pytest.raises(ValueError, match="excluded"):
        registry.describe("example:demo")
    (solar_env.workspace / ".solar/settings.json").write_text("{}")
    outside = solar_env.tmp_path / "outside.md"
    outside.write_text("private")
    (folder / "SKILL.md").unlink()
    (folder / "SKILL.md").symlink_to(outside)
    assert not registry.search("example:demo")["results"]
    with pytest.raises(ValueError, match="excluded"):
        registry.describe("example:demo")


def test_bounds_and_reference_symlinks(solar_env):
    folder = fixture_skill(solar_env)
    with pytest.raises(ValueError):
        registry.search("x" * 513)
    with pytest.raises(ValueError):
        registry.search("demo", True)
    (folder / "references").mkdir()
    outside = solar_env.tmp_path / "private.md"
    outside.write_text("private")
    (folder / "references/escape.md").symlink_to(outside)
    assert registry.describe("example:demo")["references"] == []
    (folder / "SKILL.md").write_text("---\ndescription: demo\n---\n" + "x" * 60001)
    with pytest.raises(ValueError, match="too_large"):
        registry.describe("example:demo")


def test_preference_is_not_scope_and_sync_false_is_hidden(solar_env):
    fixture_skill(solar_env, "transversal", "billing finance")
    hidden = fixture_skill(solar_env, "hidden", "billing finance")
    path = hidden / "SKILL.md"
    path.write_text(path.read_text().replace("---\nname:", "---\nsync: false\nname:", 1))
    result = registry.search("billing", preferred_namespace="another")
    assert [entry["id"] for entry in result["results"]] == ["example:transversal"]
    with pytest.raises(ValueError):
        registry.describe("example:hidden")
