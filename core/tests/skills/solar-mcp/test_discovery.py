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


def _write_skill(env, name, text):
    folder = env.workspace / "planets/example/skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text)
    return folder


def _wide_skill(env):
    filler = ("This is ordinary body text for the outline fixture. " * 50) + "\n\n"
    text = (
        "---\nname: wide\ndescription: wide synthetic skill\n---\n\n"
        "# Wide\n\nPreamble is not a section.\n\n"
        "## Purpose\n\n" + filler +
        "## Steps\n\nParent steps.\n\n"
        "### Prepare\n\nPrepare the fixture.\n\n"
        "### Run\n\nRun the fixture.\n\n"
        "## Approval gate\n\nUNIQUE_GATE_MARKER do not skip this gate.\n\n"
        "## Never rewrite\n\nLeave the original words in place.\n\n"
        "## Notes\n\n" + filler +
        "```\n## Approval gate\nUNIQUE_FAKE_GATE\n```\n"
        "UNIQUE_BODY_MARKER stays in the notes section.\n"
    )
    folder = _write_skill(env, "wide", text)
    (folder / "references").mkdir()
    (folder / "references/detail.md").write_text("Detailed fixture")
    assert len(text.encode()) > 4096
    return text


def test_small_skill_is_returned_whole(solar_env):
    folder = fixture_skill(solar_env, "tiny", "tiny skill")
    text = (folder / "SKILL.md").read_text()
    assert len(text.encode()) <= 4096
    described = registry.describe("example:tiny")
    assert described["instructions"] == text
    assert "outline" not in described
    assert "usage" not in described
    assert described == registry.describe("example:tiny", full=True)
    revision = described["revision"]
    (folder / "SKILL.md").write_text(text + "Changed\n")
    with pytest.raises(ValueError, match="revision"):
        registry.describe("example:tiny", revision, section="Purpose")


def test_outline_boundary_is_four_kibibytes(solar_env):
    def sized(name, size):
        head = f"---\nname: {name}\ndescription: sized\n---\n\n## Purpose\n\n"
        body = head + ("x" * (size - len(head.encode())))
        assert len(body.encode()) == size
        _write_skill(solar_env, name, body)
        return body

    at_limit = sized("atlimit", 4096)
    sized("overlimit", 4097)
    assert registry.describe("example:atlimit")["instructions"] == at_limit
    outlined = registry.describe("example:overlimit")
    assert outlined["outline"] is True
    assert "instructions" not in outlined
    assert outlined["sections"][0]["title"] == "Purpose"


def test_large_skill_outline_sections_and_full_body(solar_env):
    source = _wide_skill(solar_env)
    outlined = registry.describe("example:wide")
    assert outlined["outline"] is True
    assert outlined["id"] == "example:wide"
    assert outlined["description"] == "wide synthetic skill"
    assert outlined["revision"]
    assert outlined["references"] == ["references/detail.md"]
    assert "instructions" not in outlined
    titles = [(item["level"], item["title"]) for item in outlined["sections"]]
    assert titles == [
        (2, "Purpose"), (2, "Steps"), (3, "Prepare"), (3, "Run"),
        (2, "Approval gate"), (2, "Never rewrite"), (2, "Notes"),
    ]
    assert [item["title"] for item in outlined["governance_sections"]] == [
        "Approval gate", "Never rewrite"]
    dumped = json.dumps(outlined)
    assert "UNIQUE_GATE_MARKER" in dumped
    assert "Leave the original words in place." in dumped
    assert "UNIQUE_BODY_MARKER" not in dumped
    assert "UNIQUE_FAKE_GATE" not in dumped
    close = source.index("\n---\n", 4) + len("\n---\n")
    expected_preamble = source[close:source.index("## Purpose")]
    assert outlined["preamble"] == expected_preamble
    assert "Preamble is not a section." in outlined["preamble"]
    assert "## Purpose" not in outlined["preamble"]
    assert outlined["usage"] == registry._OUTLINE_USAGE
    assert len(outlined["usage"]) <= 200

    notes = registry.describe("example:wide", section="Notes")
    assert "usage" not in notes
    assert notes["instructions"].startswith("## Notes\n")
    assert "UNIQUE_BODY_MARKER" in notes["instructions"]
    assert "UNIQUE_GATE_MARKER" not in notes["instructions"]
    assert notes["instructions"] in source
    listed = next(item for item in outlined["sections"] if item["title"] == "Notes")
    assert listed["bytes"] == len(notes["instructions"].encode())
    gate = next(item for item in outlined["governance_sections"] if item["title"] == "Approval gate")
    assert gate["text"] == registry.describe("example:wide", section="Approval gate")["instructions"]
    assert gate["text"] in source
    assert gate["bytes"] == len(gate["text"].encode())

    with pytest.raises(ValueError, match="Unknown section") as missing:
        registry.describe("example:wide", section="Nope")
    assert "Purpose" in str(missing.value) and "Approval gate" in str(missing.value)

    full = registry.describe("example:wide", full=True)
    assert full["instructions"] == source
    assert "outline" not in full
    assert "usage" not in full
    assert set(full) == {
        "dependency_availability", "governance", "id", "instructions", "namespace",
        "references", "revision", "type", "unit_revision"}
    reference = registry.describe("example:wide", reference="references/detail.md")
    assert reference["instructions"] == "Detailed fixture"
    assert "outline" not in reference
    assert "usage" not in reference

    with pytest.raises(ValueError, match="does not accept a path"):
        registry.describe("example:wide", section="../Secret")
    with pytest.raises(ValueError, match="does not accept a path"):
        registry.describe("example:wide", section="references/detail.md")
    with pytest.raises(ValueError, match="does not accept a path"):
        registry.describe("example:wide", reference="../../secret.md")
    with pytest.raises(ValueError, match="cannot be combined"):
        registry.describe("example:wide", section="Notes", full=True)
    with pytest.raises(ValueError, match="boolean"):
        registry.describe("example:wide", full="yes")

    outline_bytes = len(json.dumps(outlined, indent=2, sort_keys=True).encode())
    full_bytes = len(json.dumps(full, indent=2, sort_keys=True).encode())
    # Large-fixture response JSON: heading outline (usage included) versus the complete body.
    assert (outline_bytes, full_bytes) == (1592, 6120)


def test_spanish_rule_titles_stay_in_the_outline(solar_env):
    filler = ("Texto ordinario que el esquema no debe copiar. " * 90) + "\n\n"
    text = (
        "---\nname: voz\ndescription: skill de voz en español\n---\n\n"
        "Lee esto antes de cualquier sección.\n\n"
        "## Dependencia obligatoria · la voz\n\n"
        "Hay que usar la voz canónica. No la reescribas.\n\n"
        "## Reglas duras\n\n"
        "No inventes cifras. No publiques.\n\n"
        "## Notas sueltas\n\n" + filler +
        "MARCADOR_NOTAS_ORDINARIAS queda fuera del esquema.\n"
    )
    assert len(text.encode()) > 4096
    _write_skill(solar_env, "voz", text)
    outlined = registry.describe("example:voz")
    governed = outlined["governance_sections"]
    assert [item["title"] for item in governed] == [
        "Dependencia obligatoria · la voz", "Reglas duras"]
    voice = governed[0]["text"]
    rules = governed[1]["text"]
    assert voice == registry.describe("example:voz", section="Dependencia obligatoria · la voz")["instructions"]
    assert rules == registry.describe("example:voz", section="Reglas duras")["instructions"]
    assert voice in text and rules in text
    assert "Hay que usar la voz canónica. No la reescribas." in voice
    assert "No inventes cifras. No publiques." in rules
    assert "MARCADOR_NOTAS_ORDINARIAS" not in json.dumps(outlined)
    assert outlined["preamble"] == "\nLee esto antes de cualquier sección.\n\n"
    full = registry.describe("example:voz", full=True)
    assert full["instructions"] == text
    outline_bytes = len(json.dumps(outlined, indent=2, sort_keys=True).encode())
    full_bytes = len(json.dumps(full, indent=2, sort_keys=True).encode())
    # Spanish-fixture response JSON: heading outline (usage included) versus the complete body.
    assert (outline_bytes, full_bytes) == (1365, 5013)


def test_preamble_is_complete_and_an_oversized_one_is_refused(solar_env):
    text = (
        "---\nname: lead\ndescription: preamble fixture\n---\n\n"
        "# Antes del cuerpo\n\n"
        "PREAMBULO_COMPLETO debe salir entero.\n\n"
        "## Purpose\n\n" + ("ordinary section body. " * 200) + "\n"
    )
    assert len(text.encode()) > 4096
    _write_skill(solar_env, "lead", text)
    outlined = registry.describe("example:lead")
    assert outlined["preamble"] == "\n# Antes del cuerpo\n\nPREAMBULO_COMPLETO debe salir entero.\n\n"
    assert outlined["preamble"] in text
    assert "## Purpose" not in outlined["preamble"]

    quotes = '"' * 40000
    huge = (
        "---\nname: huge\ndescription: huge preamble\n---\n"
        + quotes
        + "\n## Notes\n\nshort\n"
    )
    assert 4096 < len(huge.encode()) <= 60000
    _write_skill(solar_env, "huge", huge)
    with pytest.raises(ValueError, match="response too_large"):
        registry.describe("example:huge")


def test_outline_is_kept_only_when_under_85_percent_of_the_body(solar_env):
    source = _wide_skill(solar_env)
    outlined = registry.describe("example:wide")
    assert outlined["outline"] is True
    full = registry.describe("example:wide", full=True)
    assert full["instructions"] == source
    outline_bytes = len(json.dumps(outlined, indent=2, sort_keys=True).encode())
    full_bytes = len(json.dumps(full, indent=2, sort_keys=True).encode())
    assert "usage" in outlined and "usage" not in full
    without_usage = dict(outlined)
    without_usage.pop("usage")
    assert outline_bytes > len(json.dumps(without_usage, indent=2, sort_keys=True).encode())
    assert outline_bytes * 100 < full_bytes * 85

    rule = ("No publiques ni resumas esta regla. " * 150)
    heavy = (
        "---\nname: heavy\ndescription: rules dominate\n---\n\n"
        "## Reglas duras\n\n"
        "### Prohibido resumir\n\n"
        + rule + "\n"
    )
    assert len(heavy.encode()) > 4096
    _write_skill(solar_env, "heavy", heavy)
    returned = registry.describe("example:heavy")
    assert "outline" not in returned
    assert "usage" not in returned
    assert returned["instructions"] == heavy
    assert returned == registry.describe("example:heavy", full=True)
    # The outline JSON for this fixture, including usage, is 11,910 bytes, 200.4% of the body.
    assert len(json.dumps(returned, indent=2, sort_keys=True).encode()) == 5942


def _safety_after_fence(env, name, middle):
    filler = ("Ordinary body that the outline should omit. " * 100) + "\n\n"
    text = (
        "---\n"
        f"name: {name}\n"
        "description: fence fixture\n"
        "---\n\n"
        "## Notes\n\n" + filler + middle +
        "## Safety\n\n"
        "SAFETY_RULE must stay visible.\n"
    )
    assert len(text.encode()) > 4096
    _write_skill(env, name, text)
    outlined = registry.describe(f"example:{name}")
    assert outlined["outline"] is True
    assert "Safety" in [item["title"] for item in outlined["sections"]]
    assert "Not safety" not in [item["title"] for item in outlined["sections"]]
    governed = [item["title"] for item in outlined["governance_sections"]]
    assert "Safety" in governed
    safety = registry.describe(f"example:{name}", section="Safety")
    assert safety["instructions"].startswith("## Safety\n")
    assert "SAFETY_RULE must stay visible." in safety["instructions"]


def test_fence_length_and_mixed_markers_keep_a_later_safety_section(solar_env):
    _safety_after_fence(
        solar_env, "fourback",
        "````\n```\n## Not safety\n`````\n")
    _safety_after_fence(
        solar_env, "mixedtick",
        "```\n~~~\n## Not safety\n```\n")
    _safety_after_fence(
        solar_env, "mixedtilde",
        "~~~\n```\n## Not safety\n~~~\n")
    _safety_after_fence(
        solar_env, "inlinebt",
        "Use ```inline``` backticks and a `## Safety` mention in the paragraph.\n")
    _safety_after_fence(
        solar_env, "indentfour",
        "    ```\n    indented example without a closer\n")
    _safety_after_fence(
        solar_env, "indentthree",
        "   ```\n## Not safety\n   ```\n")


def test_marked_core_titles_stay_in_the_outline(solar_env):
    core = Path(__file__).resolve().parents[3] / "skills"
    checked = 0
    for skill in sorted(core.glob("*/SKILL.md")):
        raw = skill.read_bytes()
        if len(raw) <= 4096:
            continue
        try:
            outlined = registry.describe(skill.parent.name)
        except ValueError as exc:
            if "unavailable" in str(exc) or "excluded" in str(exc):
                continue
            raise
        if not outlined.get("outline"):
            continue
        checked += 1
        marked = [item["title"] for item in outlined["sections"] if registry._is_governance(item["title"])]
        governed = [item["title"] for item in outlined["governance_sections"]]
        assert marked == governed
        source = raw.decode("utf-8")
        for item in outlined["governance_sections"]:
            assert item["text"] in source
            assert item["bytes"] == len(item["text"].encode())
        preamble = outlined["preamble"]
        assert preamble in source
        assert "\n## " not in ("\n" + preamble)
    assert checked > 0
