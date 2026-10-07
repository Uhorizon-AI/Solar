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


def test_description_cuts_on_a_word_and_only_marks_a_cut(solar_env):
    fixture_skill(solar_env, "short", "Brief label")
    exact = ("c" * 120)
    fixture_skill(solar_env, "exactfit", exact)
    spaced = ("bravo " * 40).strip()
    fixture_skill(solar_env, "spaced", spaced)
    solid = "d" * 200
    fixture_skill(solar_env, "solid", solid)

    short = registry.search("example:short")["results"][0]
    assert short["description"] == "Brief label"
    assert "…" not in short["description"]

    fitted = registry.search("example:exactfit")["results"][0]
    assert fitted["description"] == exact
    assert not fitted["description"].endswith("…")

    clipped = registry.search("example:spaced")["results"][0]["description"]
    assert len(clipped) <= 120
    assert clipped.endswith("…")
    body = clipped[:-1]
    assert spaced.startswith(body)
    assert body == body.rstrip()
    assert spaced[len(body)].isspace()

    hard = registry.search("example:solid")["results"][0]["description"]
    assert hard == ("d" * 119) + "…"
    assert len(hard) == 120


def test_limit_defaults_to_five_and_caps_above_ten(solar_env):
    for index in range(12):
        fixture_skill(solar_env, f"page{index:02d}", f"zzpagehit item{index:02d}")
    default = registry.search("zzpagehit")
    assert len(default["results"]) == 5
    assert "limit_capped" not in default
    assert default["truncated"] is False

    page = registry.search("zzpagehit", limit=10)
    assert len(page["results"]) == 10
    assert "limit_capped" not in page

    capped = registry.search("zzpagehit", limit=25)
    assert len(capped["results"]) == 10
    assert [row["id"] for row in capped["results"]] == [row["id"] for row in page["results"]]
    assert capped["limit_capped"] is True

    with pytest.raises(ValueError, match="at least 1"):
        registry.search("zzpagehit", limit=0)
    with pytest.raises(ValueError, match="at least 1"):
        registry.search("zzpagehit", limit=-3)
    with pytest.raises(ValueError, match="at least 1"):
        registry.search("zzpagehit", True)
    with pytest.raises(ValueError, match="at least 1"):
        registry.search("zzpagehit", 1.5)


def test_exact_id_still_ranks_first(solar_env):
    fixture_skill(solar_env, "other", "target extra terms " * 20)
    fixture_skill(solar_env, "target", "unrelated label")
    found = registry.search("example:target")
    assert found["results"][0]["id"] == "example:target"
    assert found["results"][0]["revision"]
    assert found["results"][0]["description"] == "unrelated label"
    assert "path" not in found["results"][0]
    folded = registry.search("Example:Target")
    assert folded["results"][0]["id"] == "example:target"


def _search_rows(catalog, token, describe):
    rows = []
    for key, entry in sorted(catalog.items()):
        if token not in entry["description"]:
            continue
        rows.append(dict(id=key, type="instruction", namespace=entry["namespace"],
                         description=describe(entry["description"]), revision=entry["revision"],
                         matches=[token], dependency_availability="unknown"))
    return rows


def test_thirty_skill_fixture_shrinks_the_search_payload(solar_env):
    token = "zzbulkmatch"
    long = ("alpha bravo charlie delta " * 20).strip()
    assert len(long) > 400
    for index in range(30):
        fixture_skill(solar_env, f"bulk{index:02d}", f"{long} {token} n{index:02d}")
    catalog = {key: entry for key, entry in registry.entries().items() if token in entry["description"]}
    assert len(catalog) == 30
    old_rows = _search_rows(catalog, token, lambda text: text[:400])
    new_rows = _search_rows(catalog, token, registry.clip_description)
    old_bytes = len(json.dumps(dict(results=old_rows, truncated=False), indent=2, sort_keys=True).encode())
    new_bytes = len(json.dumps(dict(results=new_rows, truncated=False), indent=2, sort_keys=True).encode())
    # 30-skill result JSON: 400-character slices versus the 120-character clip.
    assert (old_bytes, new_bytes) == (21223, 12853)
    live = registry.search(token, limit=30)
    assert live["limit_capped"] is True
    assert len(live["results"]) == 10
    assert all(len(row["description"]) <= 120 and row["description"].endswith("…") for row in live["results"])
    assert live["results"][0]["revision"]


def test_preference_is_not_scope_and_sync_false_is_hidden(solar_env):
    fixture_skill(solar_env, "transversal", "billing finance")
    hidden = fixture_skill(solar_env, "hidden", "billing finance")
    path = hidden / "SKILL.md"
    path.write_text(path.read_text().replace("---\nname:", "---\nsync: false\nname:", 1))
    result = registry.search("billing", preferred_namespace="another")
    assert [entry["id"] for entry in result["results"]] == ["example:transversal"]
    with pytest.raises(ValueError):
        registry.describe("example:hidden")
