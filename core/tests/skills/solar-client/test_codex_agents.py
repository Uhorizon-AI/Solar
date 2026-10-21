"""Opt-in native Codex agent publication: serialization, ownership, exclusions, recovery.

Every test builds a temporary workspace with synthetic planets. Nothing here
touches a real Solar workspace, a real CODEX_HOME or a real runtime.
"""
import fcntl
import json
import os
import random
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

# Publishing requires Python >= 3.11 (tomllib); the suite declares >=3.10, so on
# 3.10 skip this module instead of failing collection for the whole run.
tomllib = pytest.importorskip("tomllib", reason="Codex agent publication needs Python 3.11+")

CORE = Path(__file__).resolve().parents[3]
SCRIPTS = CORE / "skills/solar-client/scripts"
SCRIPT = SCRIPTS / "codex_agents.py"
sys.path.insert(0, str(SCRIPTS))
import codex_agents as ca  # noqa: E402

PERSONAL = "personal-x"

# chmod(0) does not block reads for root, so tests that rely on an unreadable
# file/dir fail for the wrong reason (or pass vacuously) as root. Skip them.
def _volume_is_case_sensitive():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Probe").write_text("x")
        return not (Path(tmp) / "probe").exists()


# Tests that put two sources differing only by case on disk need a case-sensitive
# volume (Linux); on a case-insensitive one (default macOS) both names are one file.
CASE_SENSITIVE = _volume_is_case_sensitive()
needs_case_sensitive = pytest.mark.skipif(
    not CASE_SENSITIVE, reason="volume is case-insensitive: Lead.md and lead.md are one file")
needs_case_insensitive = pytest.mark.skipif(
    CASE_SENSITIVE, reason="volume is case-sensitive")

needs_unreadable = pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores file modes, so chmod(0) is still readable")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def contract(name, description="Maintains the synthetic result.", body="# Role\n\nDo the synthetic work.\n", extra=""):
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}"


def write_agent(ws, planet, name, text=None, raw=None):
    folder = ws / "planets" / planet / "agents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_text(text if text is not None else contract(name))
    return path


def write_settings(ws, **extra):
    data = {"core_source": "global", "layout": "solar-client-v1.2", "scope": "workspace"}
    data.update(extra)
    (ws / ".solar").mkdir(exist_ok=True)
    (ws / ".solar/settings.json").write_text(json.dumps(data, indent=2) + "\n")


def settings(ws):
    return json.loads((ws / ".solar/settings.json").read_text())


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"
    (root / "sun").mkdir(parents=True)
    write_settings(root)
    write_agent(root, "demo", "sales")
    write_agent(root, "demo", "support")
    write_agent(root, "other", "ops")
    write_agent(root, PERSONAL, "diary", contract("diary", "Private synthetic role."))
    return root


@pytest.fixture
def env(tmp_path):
    other_home = tmp_path / "external-codex-home"
    other_home.mkdir()
    (other_home / "config.toml").write_text("# external\n")
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(other_home),
        "SOLAR_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "SOLAR_APP_DATA": str(tmp_path / "app-data"),
        "SOLAR_CODEX_AGENTS_LOCK_TIMEOUT": "10",
    }


def run(ws, env, *args, extra_env=None, timeout=60):
    full = dict(env)
    if extra_env:
        full.update(extra_env)
    return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws), *args],
                          capture_output=True, text=True, env=full, timeout=timeout)


def enable(ws, env, excluded=(PERSONAL,)):
    for planet in excluded:
        assert run(ws, env, "exclude", "add", planet).returncode == 0
    assert run(ws, env, "enable").returncode == 0


def agents_dir(ws):
    return ws / ".codex/agents"


def toml_files(ws):
    d = agents_dir(ws)
    return sorted(p.name for p in d.glob("*.toml")) if d.is_dir() else []


def manifest(ws):
    return json.loads((agents_dir(ws) / ca.MANIFEST_NAME).read_text())


def snapshot(root):
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            st = os.lstat(p)
            content = None
            if stat.S_ISREG(st.st_mode):
                content = p.read_bytes()
            elif stat.S_ISLNK(st.st_mode):
                content = os.readlink(p)
            state[str(p)] = (st.st_mode, st.st_size, st.st_mtime_ns, content)
        st = os.lstat(dirpath)
        state[dirpath] = (st.st_mode, None, st.st_mtime_ns, None)
    return state


def preview_json(ws, env, *flags):
    proc = run(ws, env, "preview", "--contents", "--json", *flags)
    assert proc.returncode in (0, 3), proc.stderr
    return json.loads(proc.stdout)


def omitted(data):
    return {item["source"]: item["reason"] for item in data["omitted"]}


def conflicts(data):
    return {item["source"]: item["reason"] for item in data["conflicts"]}


def actions(data):
    return {item["file"]: item["action"] for item in data["items"]}


# --------------------------------------------------------------------------
# TOML serialization
# --------------------------------------------------------------------------

SERIAL_CASES = [
    'plain text',
    'quote " one',
    'two "" quotes',
    'triple """ quotes',
    'quad """" quotes',
    '"' * 9,
    'ends with a quote"',
    'ends with two quotes""',
    'ends with a run """',
    '"starts with a quote',
    'back\\slash and C:\\path\\n',
    'trailing backslash\\',
    '\\"""',
    'unicode: h\u00e9llo \u00f1 \u65e5\u672c\u8a9e',
    'emoji \U0001F600 \U0001F680',
    'tab\there',
    'crlf\r\nline\r\nends',
    'lone cr\rhere',
    'embedded\n\nnewlines\n',
    '\nleading newline',
    'controls \x01\x02\x07\x08\x0b\x0c\x1b\x1f and del \x7f',
    '',
    '"""\n"""\n"""',
]


@pytest.mark.parametrize("value", SERIAL_CASES)
def test_multiline_serialization_round_trips(value):
    doc = f"v = {ca.toml_multiline_string(value)}\n"
    parsed = tomllib.loads(doc)["v"]
    assert parsed == value.replace("\r\n", "\n").replace("\r", "\n")


@pytest.mark.parametrize("value", [v for v in SERIAL_CASES])
def test_single_line_serialization_round_trips(value):
    doc = f"v = {ca.toml_basic_string(value)}\n"
    assert "\n" not in ca.toml_basic_string(value)
    assert tomllib.loads(doc)["v"] == value


def test_serialization_fuzz():
    rng = random.Random(7)
    alphabet = ['"', '"', '"', "\\", "\n", "\r", "\t", "a", "b", " ", "\u00e9", "\U0001F600", "\x00"[:0] or "c", "\x1b", "\x7f"]
    for _ in range(400):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        doc = f"v = {ca.toml_multiline_string(value)}\n"
        assert tomllib.loads(doc)["v"] == value.replace("\r\n", "\n").replace("\r", "\n")


def test_generated_file_has_closed_field_list(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "tricky", contract(
        "tricky", 'Quotes "here" and \\ slashes', 'Body with """ triple\nand a trailing quote "\n'))
    assert run(ws, env, "publish").returncode == 0
    for name in toml_files(ws):
        parsed = tomllib.loads((agents_dir(ws) / name).read_text())
        assert set(parsed) == {"name", "description", "developer_instructions"}
        assert parsed["name"] + ".toml" == name
        for forbidden in ("sandbox", "approval", "mcp", "network", "model", "credentials"):
            assert forbidden not in set(parsed)
    tricky = tomllib.loads((agents_dir(ws) / "demo:tricky.toml").read_text())
    assert tricky["description"] == 'Quotes "here" and \\ slashes'
    assert 'Body with """ triple\nand a trailing quote "\n' in tricky["developer_instructions"]
    assert "does not grant" not in tricky["developer_instructions"]
    assert "grants no authority" in tricky["developer_instructions"]
    assert "planets/demo/agents/tricky.md" in tricky["developer_instructions"]


def test_body_crlf_is_normalized_to_lf(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "crlf", raw=b"---\r\nname: crlf\r\ndescription: Windows line endings\r\n---\r\n\r\nline one\r\nline two\r\n")
    assert run(ws, env, "publish").returncode == 0
    text = tomllib.loads((agents_dir(ws) / "demo:crlf.toml").read_text())["developer_instructions"]
    assert "line one\nline two\n" in text and "\r" not in text


# --------------------------------------------------------------------------
# Contract validation
# --------------------------------------------------------------------------

BAD = {
    "nofm": (b"# just markdown\n", "no frontmatter"),
    "unclosed": (b"---\nname: unclosed\ndescription: x\n\nbody\n", "unclosed frontmatter"),
    "noname": (b"---\ndescription: x\n---\nbody\n", "no name"),
    "nodesc": (b"---\nname: nodesc\n---\nbody\n", "no description"),
    "mismatch": (b"---\nname: other\ndescription: x\n---\nbody\n", "does not match"),
    "badchars": (b"---\nname: 'bad name'\ndescription: x\n---\nbody\n", "characters outside"),
    "emptybody": (b"---\nname: emptybody\ndescription: x\n---\n\n  \n", "empty body"),
    "nul": (b"---\nname: nul\ndescription: x\n---\nbo\x00dy\n", "NUL"),
    "badutf8": (b"---\nname: badutf8\ndescription: x\n---\nbo\xff\xfedy\n", "UTF-8"),
    "huge": (b"---\nname: huge\ndescription: x\n---\n" + b"a" * (300 * 1024), "256 KiB"),
    "dupkeys": (b"---\nname: dupkeys\nname: dupkeys\ndescription: x\n---\nbody\n", "duplicate"),
    "dupother": (b"---\nname: dupother\ndescription: x\ntools: a\ntools: b\n---\nbody\n", "duplicate"),
    "longdesc": (("---\nname: longdesc\ndescription: " + "word " * 300 + "\n---\nbody\n").encode(), "1024"),
}


@pytest.mark.parametrize("stem", sorted(BAD))
def test_invalid_contracts_are_omitted_with_reason(ws, env, stem):
    raw, expected = BAD[stem]
    write_agent(ws, "demo", stem, raw=raw)
    data = preview_json(ws, env)
    source = f"planets/demo/agents/{stem}.md"
    assert expected in omitted(data)[source]
    assert all(item["source"] != source for item in data["items"])
    # Other agents are not affected.
    assert "demo:sales.toml" in actions(data)


def test_valid_scalar_forms(ws, env):
    write_agent(ws, "demo", "folded", "---\nname: folded\ndescription: >\n  First part\n  second part.\n---\nbody\n")
    write_agent(ws, "demo", "literal", "---\nname: literal\ndescription: |\n  First\n  second\n---\nbody\n")
    write_agent(ws, "demo", "dq", '---\nname: "dq"\ndescription: "Quoted \\"x\\" here"\n---\nbody\n')
    write_agent(ws, "demo", "sq", "---\nname: 'sq'\ndescription: 'It''s fine'\ntools: [a, b]\n---\nbody\n")
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    desc = lambda n: tomllib.loads((agents_dir(ws) / f"demo:{n}.toml").read_text())["description"]
    assert desc("folded") == "First part second part."
    assert desc("literal") == "First second"
    assert desc("dq") == 'Quoted "x" here'
    assert desc("sq") == "It's fine"


def test_ignored_files_and_nested_agents_are_never_published(ws, env):
    enable(ws, env)
    folder = ws / "planets/demo/agents"
    (folder / "README.md").write_text(contract("README"))
    (folder / "readme.md").write_text(contract("readme"))
    (folder / ".hidden.md").write_text(contract(".hidden"))
    (folder / "_template.md").write_text(contract("_template"))
    (folder / "notes.txt").write_text("not markdown")
    for nested in ("skills/foo/agents", "continuidad", "lecciones", "references", "agents/sub"):
        d = ws / "planets/demo" / nested
        d.mkdir(parents=True, exist_ok=True)
        (d / "nested.md").write_text(contract("nested"))
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws) == ["demo:sales.toml", "demo:support.toml", "other:ops.toml"]
    out = run(ws, env, "publish").stdout
    assert "nested" not in out and "README" not in out and "hidden" not in out


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def test_published_name_is_planet_colon_agent_verbatim(ws, env):
    write_agent(ws, "demo", "Sales-Lead_2.v1", contract("Sales-Lead_2.v1"))
    write_agent(ws, "demo", "trail_", contract("trail_"))
    data = preview_json(ws, env)
    assert actions(data)["demo:Sales-Lead_2.v1.toml"] == "add"
    assert actions(data)["demo:trail_.toml"] == "add"


def test_name_file_stem_and_identity_come_from_one_function(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    for entry in manifest(ws)["agents"]:
        planet, agent = entry["source"].split("/")[1], entry["source"].split("/")[3][:-3]
        assert entry["name"] == entry["identity"] == ca.canonical_identity(planet, agent)
        assert entry["file"] == entry["name"] + ".toml"
        parsed = tomllib.loads((agents_dir(ws) / entry["file"]).read_text())
        assert parsed["name"] == entry["name"]


def test_hyphen_and_underscore_are_distinct_published_names(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "uh-sales", contract("uh-sales"))
    write_agent(ws, "demo", "uh_sales", contract("uh_sales"))
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout
    assert {"demo:uh-sales.toml", "demo:uh_sales.toml"} <= set(toml_files(ws))


@pytest.mark.parametrize("planet,agent,why", [
    ("demo", "a b", "characters outside"),
    ("demo", "a:b", "contains ':'"),
    ("my:planet", "a", "contains ':'"),
    ("-lead", "a", "starts with '-', '.' or '_'"),
    ("demo", "-lead", "starts with '-', '.' or '_'"),
    ("_p", "a", "starts with '-', '.' or '_'"),
    ("demo", "caf\u00e9", "characters outside"),
    ("demo", "x" * 65, "longer than 64"),
    ("p" * 65, "a", "longer than 64"),
])
def test_invalid_components_are_rejected_with_reason_and_never_substituted(ws, env, planet, agent, why):
    enable(ws, env)
    write_agent(ws, planet, agent, contract(agent))
    data = preview_json(ws, env)
    source = f"planets/{planet}/agents/{agent}.md"
    reason = omitted(data).get(source) or omitted(data)[f"planets/{planet}"]
    assert why in reason and "nothing is substituted" in reason
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws) == ["demo:sales.toml", "demo:support.toml", "other:ops.toml"]


def test_canonical_identity_rejects_unsafe_components():
    assert ca.canonical_identity("uhorizon", "uh-backend-dev") == "uhorizon:uh-backend-dev"
    assert ca.canonical_identity("louis", "lou-ai") == "louis:lou-ai"
    for planet, agent in [("a:b", "c"), ("a", "b:c"), ("a/b", "c"), ("a", "b/c"), ("", "c"), (".", "c"),
                          ("..", "c"), ("a", "-b"), ("a", ".b"), ("a", "_b"), ("a", "b" * 65)]:
        with pytest.raises(ca.ContractError):
            ca.canonical_identity(planet, agent)


def test_role_name_serializes_with_colon_hyphen_and_unicode_body(ws, env):
    enable(ws, env)
    description = 'Descripci\u00f3n "con comillas" \\ y \u65e5\u672c\u8a9e'
    body = '# Rol\n\nTexto con \u00f1, emoji \U0001F680, """triple""" y\r\nsalto CRLF\n\n\tTab y "comillas"\n'
    write_agent(ws, "uhorizon", "uh-backend-dev", contract("uh-backend-dev", description, body))
    write_agent(ws, "louis", "lou-ai", contract("lou-ai"))
    assert run(ws, env, "publish").returncode == 0
    path = agents_dir(ws) / "uhorizon:uh-backend-dev.toml"
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert set(parsed) == {"name", "description", "developer_instructions"}
    assert parsed["name"] == "uhorizon:uh-backend-dev"
    assert parsed["description"] == description
    assert body.replace("\r\n", "\n") in parsed["developer_instructions"]
    assert "`uhorizon:uh-backend-dev`" in parsed["developer_instructions"]
    assert "solar__" not in path.read_text()
    assert (agents_dir(ws) / "louis:lou-ai.toml").is_file()
    assert 'name = "uhorizon:uh-backend-dev"' in path.read_text()


# --------------------------------------------------------------------------
# Collisions and ownership
# --------------------------------------------------------------------------

def synthetic_eligible(planet, agent):
    name = ca.canonical_identity(planet, agent)
    return ca.Eligible(planet, agent, f"planets/{planet}/agents/{agent}.md", name, name, f"{name}.toml",
                       "0" * 64, f"data {name}".encode(), "d", "i")


@pytest.mark.parametrize("first,second", [(("demo", "Lead"), ("demo", "lead")),
                                          (("Zed", "c"), ("zed", "c"))])
def test_case_only_collisions_are_detected_without_touching_the_disk(first, second):
    """Independent of the volume: the grouping works on the sources, not on files."""
    scan = ca.Scan(eligible=[synthetic_eligible(*first), synthetic_eligible(*second),
                             synthetic_eligible("demo", "other")])
    plan = ca.build_plan(scan, ca.Dest())
    assert sorted(src for src, _ in plan.conflicts) == sorted(
        f"planets/{p}/agents/{a}.md" for p, a in (first, second))
    assert all("same public name as" in why for _, why in plan.conflicts)
    assert [item.file for item, _ in plan.writes] == ["demo:other.toml"]


@needs_case_sensitive
def test_agent_names_differing_only_by_case_collide_on_disk(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "Lead", contract("Lead"))
    write_agent(ws, "demo", "lead", contract("lead"))
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert not [n for n in toml_files(ws) if n.lower() == "demo:lead.toml"]
    assert proc.stdout.count("conflict:") == 2 and "same public name as" in proc.stdout
    assert "demo:sales.toml" in toml_files(ws)


@needs_case_sensitive
def test_planet_names_differing_only_by_case_collide_on_disk(ws, env):
    enable(ws, env)
    write_agent(ws, "Zed", "c", contract("c"))
    write_agent(ws, "zed", "c", contract("c"))
    assert run(ws, env, "publish").returncode == 3
    assert not [n for n in toml_files(ws) if n.lower() == "zed:c.toml"]


@needs_case_insensitive
def test_case_variant_sources_are_one_file_on_a_case_insensitive_volume(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "Lead", contract("Lead"))
    write_agent(ws, "demo", "lead", contract("lead"))  # same file: only one source exists
    assert run(ws, env, "publish").returncode in (0, 3)
    assert len([n for n in toml_files(ws) if n.lower() == "demo:lead.toml"]) <= 1


def test_case_only_rename_retires_then_publishes_on_the_next_run(ws, env):
    """Documented behavior: the case-variant guard defers the new role by one run."""
    enable(ws, env)
    folder = ws / "planets/demo/agents"
    (folder / "Lead.md").write_text(contract("Lead"))
    assert run(ws, env, "publish").returncode == 0
    (folder / "Lead.md").unlink()
    (folder / "lead.md").write_text(contract("lead"))
    proc = run(ws, env, "publish")
    assert proc.returncode == 3 and "differs only by letter case" in proc.stdout
    assert "demo:Lead.toml" not in toml_files(ws) and "demo:lead.toml" not in toml_files(ws)
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout
    assert [n for n in toml_files(ws) if n.lower() == "demo:lead.toml"] == ["demo:lead.toml"]
    assert_converged(ws, env)


def test_case_variant_foreign_file_blocks(ws, env):
    agents_dir(ws).mkdir(parents=True)
    foreign = agents_dir(ws) / "DEMO:sales.toml"
    foreign.write_text('name = "DEMO:sales"\ndescription = "m"\ndeveloper_instructions = "x"\n')
    before = foreign.read_bytes()
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert foreign.read_bytes() == before
    assert "demo:sales.toml" not in os.listdir(agents_dir(ws))
    assert "planets/demo/agents/sales.md" in conflicts(preview_json(ws, env))


def test_foreign_toml_with_same_name_blocks(ws, env):
    agents_dir(ws).mkdir(parents=True)
    foreign = agents_dir(ws) / "mine.toml"
    foreign.write_text('name = "demo:sales"\ndescription = "m"\ndeveloper_instructions = "x"\n')
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 3
    assert "demo:sales.toml" not in toml_files(ws)
    assert "demo:support.toml" in toml_files(ws)


def test_config_toml_agent_table_blocks_and_is_untouched(ws, env):
    (ws / ".codex").mkdir()
    config = ws / ".codex/config.toml"
    config.write_text('[agents."DEMO:Sales"]\ndescription = "x"\n[agents]\nmax_threads = 3\n')
    before = config.read_bytes()
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 3
    assert "demo:sales.toml" not in toml_files(ws)
    assert "demo:support.toml" in toml_files(ws)
    assert config.read_bytes() == before


@pytest.mark.parametrize("kind", ["dir", "symlink", "file"])
def test_target_path_not_ours_is_a_conflict(ws, env, kind, tmp_path):
    agents_dir(ws).mkdir(parents=True)
    target = agents_dir(ws) / "demo:sales.toml"
    outside = tmp_path / "outside.toml"
    outside.write_text("outside\n")
    if kind == "dir":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(outside)
    else:
        target.write_text("unmanaged\n")
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 3
    assert outside.read_text() == "outside\n"
    if kind == "file":
        assert target.read_text() == "unmanaged\n"
    assert "demo:support.toml" in toml_files(ws)


def test_unmanaged_file_with_generation_mark_is_not_adopted(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    (agents_dir(ws) / ca.MANIFEST_NAME).unlink()
    before = (agents_dir(ws) / "demo:sales.toml").read_bytes()
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert "generation mark" in proc.stdout
    assert (agents_dir(ws) / "demo:sales.toml").read_bytes() == before


def test_foreign_toml_referencing_contract_blocks_that_agent(ws, env):
    agents_dir(ws).mkdir(parents=True)
    manual = agents_dir(ws) / "manual_sales.toml"
    manual.write_text('name = "manual_sales"\ndescription = "m"\ndeveloper_instructions = "Read planets/demo/agents/sales.md first"\n')
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert "demo:sales.toml" not in toml_files(ws)
    assert "demo:support.toml" in toml_files(ws)
    assert "references this contract" in proc.stdout


def test_manual_agent_untouched_and_identity_exclusion(ws, env):
    agents_dir(ws).mkdir(parents=True)
    manual = agents_dir(ws) / "uh_sales.toml"
    manual.write_text('name = "uh_sales"\ndescription = "Manual role"\ndeveloper_instructions = "Hand written"\n')
    before = (manual.read_bytes(), os.stat(manual).st_mtime_ns)
    enable(ws, env)
    assert run(ws, env, "exclude", "add", "demo:sales").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    assert (manual.read_bytes(), os.stat(manual).st_mtime_ns) == before
    assert "demo:sales.toml" not in toml_files(ws)
    assert "demo:support.toml" in toml_files(ws)
    data = preview_json(ws, env)
    assert omitted(data)["planets/demo/agents/sales.md"] == "excluded by identity"


def test_identity_exclusion_is_case_and_separator_insensitive(ws, env):
    write_agent(ws, "demo", "sales-lead", contract("sales-lead"))
    assert run(ws, env, "exclude", "add", "Demo:Sales_Lead").returncode == 0
    data = preview_json(ws, env)
    assert omitted(data)["planets/demo/agents/sales-lead.md"] == "excluded by identity"
    assert run(ws, env, "exclude", "remove", "demo:sales-lead").returncode == 0
    assert settings(ws)["codex_agents"]["exclude_agents"] == []


# --------------------------------------------------------------------------
# Exclusions
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["global", "codex", "mixed"])
def test_planet_exclusions(ws, env, mode):
    if mode == "global":
        write_settings(ws, sync_exclude_planets=[PERSONAL])
    elif mode == "codex":
        run(ws, env, "exclude", "add", PERSONAL)
    else:
        write_settings(ws, sync_exclude_planets=["other"])
        run(ws, env, "exclude", "add", PERSONAL)
    assert run(ws, env, "enable").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    files = toml_files(ws)
    assert "personal-x:diary.toml" not in files
    if mode == "mixed":
        assert "other:ops.toml" not in files
    else:
        assert "other:ops.toml" in files
    assert PERSONAL.replace("-", "_") not in json.dumps(manifest(ws))


def test_planet_exclusion_is_case_insensitive(ws, env):
    write_settings(ws, sync_exclude_planets=["PERSONAL-X"])
    assert run(ws, env, "enable").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    assert "personal-x:diary.toml" not in toml_files(ws)


def test_reference_to_excluded_planet_omits_agent_with_explanation(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "ref-path", contract("ref-path", body="Read planets/personal-x/notes.md\n"))
    write_agent(ws, "demo", "ref-rel", contract("ref-rel", body="See ../Personal-X/notes.md\n"))
    write_agent(ws, "demo", "ref-id", contract("ref-id", body="Delegate to personal-x:diary when needed\n"))
    write_agent(ws, "demo", "ref-desc", contract("ref-desc", description="Works with personal-x:diary"))
    write_agent(ws, "demo", "ref-near", contract("ref-near", body="Mentions planets/personal-xl/notes.md and a personal-x word\n"))
    data = preview_json(ws, env)
    reasons = omitted(data)
    for stem in ("ref-path", "ref-rel", "ref-id", "ref-desc"):
        assert reasons[f"planets/demo/agents/{stem}.md"] == "references excluded planet personal-x"
    assert "demo:ref-near.toml" in actions(data)


# --------------------------------------------------------------------------
# Audit hook: excluded planets are never touched
# --------------------------------------------------------------------------

AUDIT_DRIVER = textwrap.dedent('''
    import json, os, runpy, sys
    log_path = os.environ["AUDIT_LOG"]
    seen = []
    def hook(event, args):
        if event in ("open", "os.listdir", "os.scandir", "glob.glob", "os.walk"):
            first = args[0] if args else None
            if isinstance(first, (str, bytes, os.PathLike)):
                seen.append([event, os.fsdecode(first)])
    sys.addaudithook(hook)
    code = 0
    try:
        sys.argv = sys.argv[1:]
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    with open(log_path, "w") as fh:
        json.dump(seen, fh)
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)
''')


def audited(ws, env, tmp_path, *args):
    driver = tmp_path / "audit_driver.py"
    driver.write_text(AUDIT_DRIVER)
    log = tmp_path / f"audit-{abs(hash(args))}.json"
    proc = subprocess.run([sys.executable, str(driver), str(SCRIPT), "--workspace", str(ws), *args],
                          capture_output=True, text=True, env=dict(env, AUDIT_LOG=str(log)), timeout=60)
    return proc, json.loads(log.read_text())


def touched_planet(seen, planet):
    """Audit events that opened, listed or walked anything under planets/<planet>.
    Published files are named after the planet (<planet>:<agent>.toml) and live under
    .codex/agents, so the planets/ path prefix is what identifies a source access."""
    marker = f"/planets/{planet}"
    return [s for s in seen if s[1].endswith(marker) or f"{marker}/" in s[1]]


@pytest.mark.parametrize("args", [
    ("publish",), ("preview",), ("preview", "--contents"), ("preview", "--contents", "--json"),
    ("status",), ("enable",),
])
def test_excluded_planet_is_never_touched(ws, env, tmp_path, args):
    run(ws, env, "exclude", "add", PERSONAL)
    if args != ("enable",):
        assert run(ws, env, "enable").returncode == 0
    proc, seen = audited(ws, env, tmp_path, *args)
    assert proc.returncode == 0, proc.stderr
    assert not touched_planet(seen, PERSONAL), seen
    if (ws / ".codex/agents").exists():
        written = "".join(p.read_text() for p in (ws / ".codex/agents").glob("*") if p.is_file())
        assert PERSONAL.replace("-", "_") not in written and PERSONAL not in written
    if args in (("publish",), ("preview", "--contents"), ("preview", "--contents", "--json")):
        assert any("planets/demo/agents" in s[1] for s in seen)


def test_excluded_planet_survives_chmod_000(ws, env):
    enable(ws, env)
    planet = ws / "planets" / PERSONAL
    os.chmod(planet, 0)
    try:
        assert run(ws, env, "publish").returncode == 0
        assert run(ws, env, "preview", "--contents").returncode == 0
        assert run(ws, env, "preview").returncode == 0
        assert "demo:sales.toml" in toml_files(ws)
    finally:
        os.chmod(planet, 0o755)


def test_disabled_by_default_reads_nothing(ws, env, tmp_path):
    proc, seen = audited(ws, env, tmp_path, "publish")
    assert proc.returncode == 0
    assert "disabled" in proc.stdout
    assert not (ws / ".codex").exists()
    assert not [s for s in seen if str(ws / "planets") in s[1] or ".codex" in s[1]], seen


def test_disabled_publish_with_nonexistent_planets_dir(tmp_path, env):
    root = tmp_path / "bare"
    (root / ".solar").mkdir(parents=True)
    assert run(root, env, "publish").returncode == 0
    assert not (root / ".codex").exists()


def test_retire_when_source_planet_excluded_later_never_reads_it(ws, env, tmp_path):
    assert run(ws, env, "enable").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    assert "personal-x:diary.toml" in toml_files(ws)
    run(ws, env, "exclude", "add", PERSONAL)
    proc, seen = audited(ws, env, tmp_path, "publish")
    assert proc.returncode == 0, proc.stderr
    assert "personal-x:diary.toml" not in toml_files(ws)
    assert not touched_planet(seen, PERSONAL), seen
    assert "retire: personal-x:diary.toml" in proc.stdout


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def test_disabled_by_default_and_publish_creates_nothing(ws, env):
    assert run(ws, env, "status").stdout.splitlines()[0] == "Codex agents: disabled"
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "disabled" in proc.stdout
    assert not (ws / ".codex").exists()


def test_enable_disable_exclude_round_trip_preserves_keys(ws, env):
    write_settings(ws, custom_user="y", sync_exclude_planets=["other"], agents_skill_profile={"mode": "native"})
    (ws / ".solar/settings.json").write_text(json.dumps(
        dict(settings(ws), codex_agents={"enabled": False, "exclude_planets": [], "exclude_agents": []})))
    assert run(ws, env, "exclude", "add", "demo").returncode == 0
    assert run(ws, env, "exclude", "add", "demo:sales").returncode == 0
    assert run(ws, env, "exclude", "add", "demo").stdout.startswith("OK: already")
    assert run(ws, env, "enable").returncode == 0
    data = settings(ws)
    assert data["custom_user"] == "y" and data["sync_exclude_planets"] == ["other"]
    assert data["agents_skill_profile"] == {"mode": "native"}
    assert data["codex_agents"] == {"enabled": True, "exclude_planets": ["demo"], "exclude_agents": ["demo:sales"]}
    listing = run(ws, env, "exclude", "list").stdout.split("\n")
    assert listing[:2] == ["planet: demo", "agent: demo:sales"]
    # Global exclusions (which also apply to Codex agents) are shown last.
    assert listing[2] == "planet: other (global, applies to Codex agents too)"
    assert run(ws, env, "disable").returncode == 0
    assert settings(ws)["codex_agents"]["enabled"] is False
    assert run(ws, env, "exclude", "remove", "demo").returncode == 0
    assert run(ws, env, "exclude", "remove", "demo:sales").returncode == 0
    assert run(ws, env, "exclude", "list").stdout.strip() == (
        "planet: other (global, applies to Codex agents too)")
    assert settings(ws)["custom_user"] == "y"


def test_exclude_list_shows_labeled_entries_and_globals(ws, env):
    write_settings(ws, sync_exclude_planets=["gplanet"])
    run(ws, env, "exclude", "add", "demo")
    run(ws, env, "exclude", "add", "demo:sales")
    out = run(ws, env, "exclude", "list").stdout.split("\n")
    assert out[:3] == [
        "planet: demo",
        "agent: demo:sales",
        "planet: gplanet (global, applies to Codex agents too)",
    ]


def test_legacy_manifest_is_read_and_removed_on_write(ws, env):
    (ws / ".solar/settings.json").unlink()
    (ws / ".solar/manifest.json").write_text(json.dumps({"layout": "solar-client-v1.1", "keep": 1}))
    assert run(ws, env, "enable").returncode == 0
    assert not (ws / ".solar/manifest.json").exists()
    assert settings(ws)["keep"] == 1 and settings(ws)["codex_agents"]["enabled"] is True


@pytest.mark.parametrize("block", [
    {"enabled": "yes"},
    {"enabled": True, "surprise": 1},
    {"exclude_planets": "demo"},
    {"exclude_planets": ["bad/id"]},
    {"exclude_planets": [3]},
    {"exclude_agents": ["noseparator"]},
    {"exclude_agents": ["a:b:c"]},
    {"exclude_agents": ["a:b c"]},
    "not-an-object",
])
def test_invalid_codex_agents_settings_exit_2(ws, env, block):
    write_settings(ws, codex_agents=block)
    for cmd in (("status",), ("publish",), ("preview",), ("exclude", "list")):
        proc = run(ws, env, *cmd)
        assert proc.returncode == 2, (cmd, proc.stdout, proc.stderr)
        assert "codex_agents" in proc.stderr
    assert not (ws / ".codex").exists()


def test_invalid_global_exclusion_and_corrupt_settings_exit_2(ws, env):
    write_settings(ws, sync_exclude_planets="demo")
    assert run(ws, env, "status").returncode == 2
    (ws / ".solar/settings.json").write_text("{not json")
    assert run(ws, env, "publish").returncode == 2


@pytest.mark.parametrize("target", ["bad/id", "..", "a:b:c", "x y"])
def test_exclude_rejects_bad_ids(ws, env, target):
    assert run(ws, env, "exclude", "add", target).returncode == 2
    assert "codex_agents" not in settings(ws)


# --------------------------------------------------------------------------
# Unsafe links
# --------------------------------------------------------------------------

def test_symlinked_codex_dir_is_refused(ws, env, tmp_path):
    enable(ws, env)
    external = tmp_path / "external"
    external.mkdir()
    (ws / ".codex").symlink_to(external)
    before = snapshot(external)
    proc = run(ws, env, "publish")
    assert proc.returncode == 5
    assert snapshot(external) == before
    assert run(ws, env, "preview", "--contents").returncode == 5


def test_symlinked_agents_dir_is_refused(ws, env, tmp_path):
    enable(ws, env)
    external = tmp_path / "external-agents"
    external.mkdir()
    (ws / ".codex").mkdir()
    (ws / ".codex/agents").symlink_to(external)
    assert run(ws, env, "publish").returncode == 5
    assert list(external.iterdir()) == []


def test_codex_path_not_a_directory_is_refused(ws, env):
    enable(ws, env)
    (ws / ".codex").write_text("file")
    assert run(ws, env, "publish").returncode == 5


def test_source_file_symlink_is_omitted(ws, env, tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text(contract("linked", "Outside description"))
    (ws / "planets/demo/agents/linked.md").symlink_to(secret)
    data = preview_json(ws, env)
    assert "unsafe link" in omitted(data)["planets/demo/agents/linked.md"]


def test_agents_dir_symlink_is_omitted(ws, env, tmp_path):
    outside = tmp_path / "outside-agents"
    outside.mkdir()
    (outside / "x.md").write_text(contract("x"))
    (ws / "planets/linked/").mkdir(parents=True)
    (ws / "planets/linked/agents").symlink_to(outside)
    data = preview_json(ws, env)
    assert omitted(data)["planets/linked/agents"] == "unsafe link"
    assert all("linked" not in i["file"] for i in data["items"])


def test_planet_symlink_escaping_planets_is_skipped(ws, env, tmp_path):
    outside = tmp_path / "outside-planet"
    write_agent(outside.parent, outside.name, "evil", contract("evil"))
    (ws / "planets/escape").symlink_to(outside)
    data = preview_json(ws, env)
    assert "unsafe link" in omitted(data)["planets/escape"]
    assert all("evil" not in i["file"] for i in data["items"])


def test_planet_symlink_to_excluded_planet_is_skipped(ws, env):
    run(ws, env, "exclude", "add", PERSONAL)
    (ws / "planets/alias").symlink_to(ws / "planets" / PERSONAL)
    data = preview_json(ws, env)
    assert all("diary" not in i["file"] for i in data["items"])


# --------------------------------------------------------------------------
# Retire
# --------------------------------------------------------------------------

def test_retire_unchanged_file_when_source_removed(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    (ws / "planets/demo/agents/support.md").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "retire: demo:support.toml" in proc.stdout
    assert "demo:support.toml" not in toml_files(ws)
    assert [e["file"] for e in manifest(ws)["agents"]] == ["demo:sales.toml", "other:ops.toml"]


def test_invalid_contract_keeps_published_file(ws, env):
    """Editing a contract into an invalid state must not delete the role."""
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "demo:support.toml"
    before = target.read_bytes()
    (ws / "planets/demo/agents/support.md").write_text("no frontmatter now\n")
    proc = run(ws, env, "publish")
    assert proc.returncode == 0
    assert "demo:support.toml" in toml_files(ws)
    assert target.read_bytes() == before
    assert "omitted: planets/demo/agents/support.md: no frontmatter" in proc.stdout
    assert "kept: contract is invalid" in proc.stdout


@pytest.mark.parametrize("broken", [
    "no frontmatter now\n",
    b"---\nname: support\ndescription: x\n---\n\n  \n",
    b"---\nname: support\ndescription: x\n---\n\nbo\x00dy\n",
])
def test_invalid_contracts_never_retire(ws, env, broken):
    enable(ws, env)
    run(ws, env, "publish")
    path = ws / "planets/demo/agents/support.md"
    if isinstance(broken, bytes):
        path.write_bytes(broken)
    else:
        path.write_text(broken)
    assert run(ws, env, "publish").returncode == 0
    assert "demo:support.toml" in toml_files(ws)


def test_removing_invalid_contract_then_retires(ws, env):
    """Once the invalid .md disappears, the kept file is finally retired."""
    enable(ws, env)
    run(ws, env, "publish")
    (ws / "planets/demo/agents/support.md").write_text("no frontmatter now\n")
    assert run(ws, env, "publish").returncode == 0
    assert "demo:support.toml" in toml_files(ws)
    (ws / "planets/demo/agents/support.md").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "retire: demo:support.toml" in proc.stdout
    assert "demo:support.toml" not in toml_files(ws)


def test_invalid_contract_then_excluded_retires(ws, env):
    """An invalid contract whose planet is later excluded is retired, not kept."""
    enable(ws, env)
    run(ws, env, "publish")
    (ws / "planets/demo/agents/support.md").write_text("no frontmatter now\n")
    assert run(ws, env, "publish").returncode == 0
    assert run(ws, env, "exclude", "add", "demo").returncode == 0
    proc = run(ws, env, "publish")
    assert proc.returncode == 0
    assert "demo:support.toml" not in toml_files(ws)
    assert "demo:sales.toml" not in toml_files(ws)


def test_rename_publishes_new_name_and_retires_old_in_one_run(ws, env):
    enable(ws, env)
    folder = ws / "planets/demo/agents"
    (folder / "foo-bar.md").write_text(contract("foo-bar"))
    assert run(ws, env, "publish").returncode == 0
    assert "demo:foo-bar.toml" in toml_files(ws)
    (folder / "foo-bar.md").unlink()
    (folder / "foo_bar.md").write_text(contract("foo_bar"))
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "demo:foo-bar.toml" not in toml_files(ws)
    assert "demo:foo_bar.toml" in toml_files(ws)
    assert [e["identity"] for e in manifest(ws)["agents"] if e["file"] == "demo:foo_bar.toml"] == ["demo:foo_bar"]
    assert_converged(ws, env)


def test_rename_across_planets_retires_old_and_adds_new(ws, env):
    enable(ws, env)
    write_agent(ws, "other", "foo-bar", contract("foo-bar"))
    assert run(ws, env, "publish").returncode == 0
    (ws / "planets/other/agents/foo-bar.md").unlink()
    write_agent(ws, "demo", "foo-bar", contract("foo-bar"))
    assert run(ws, env, "publish").returncode == 0
    assert "other:foo-bar.toml" not in toml_files(ws)
    assert "demo:foo-bar.toml" in toml_files(ws)


def test_retire_with_excluded_planet_never_reads_it(ws, env, tmp_path):
    enable(ws, env)
    write_agent(ws, "demo", "foo-bar", contract("foo-bar"))
    assert run(ws, env, "publish").returncode == 0
    (ws / "planets/demo/agents/foo-bar.md").unlink()
    write_agent(ws, "other", "foo-bar", contract("foo-bar"))
    assert run(ws, env, "exclude", "add", "demo").returncode == 0
    proc, seen = audited(ws, env, tmp_path, "publish")
    assert proc.returncode == 0
    assert not touched_planet(seen, "demo"), seen
    assert "demo:foo-bar.toml" not in toml_files(ws)
    assert "other:foo-bar.toml" in toml_files(ws)


def test_interrupted_rename_converges(ws, env):
    enable(ws, env)
    folder = ws / "planets/demo/agents"
    (folder / "foo-bar.md").write_text(contract("foo-bar"))
    assert run(ws, env, "publish").returncode == 0
    (folder / "foo-bar.md").unlink()
    (folder / "foo_bar.md").write_text(contract("foo_bar"))
    proc = run(ws, env, "publish", extra_env={"SOLAR_CODEX_AGENTS_TEST_FAIL_AFTER": "1"})
    assert proc.returncode != 0
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws).count("demo:foo_bar.toml") == 1
    assert "demo:foo-bar.toml" not in toml_files(ws)
    entries = manifest(ws)["agents"]
    assert len({e["file"] for e in entries}) == len(entries)
    assert_converged(ws, env)


def test_invalid_old_contract_keeps_its_role_while_new_stem_publishes(ws, env):
    enable(ws, env)
    folder = ws / "planets/demo/agents"
    (folder / "foo-bar.md").write_text(contract("foo-bar"))
    assert run(ws, env, "publish").returncode == 0
    original = (agents_dir(ws) / "demo:foo-bar.toml").read_bytes()
    (folder / "foo-bar.md").write_text("no frontmatter now\n")
    (folder / "foo_bar.md").write_text(contract("foo_bar"))
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (agents_dir(ws) / "demo:foo-bar.toml").read_bytes() == original
    assert "demo:foo_bar.toml" in toml_files(ws)


def test_user_edited_file_is_kept_and_reported_on_retire(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "demo:support.toml"
    target.write_text(target.read_text() + "# user note\n")
    (ws / "planets/demo/agents/support.md").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 3 and "cannot retire" in proc.stdout
    assert target.exists() and "# user note" in target.read_text()
    assert "demo:support.toml" in [e["file"] for e in manifest(ws)["agents"]]


def test_mark_stripped_file_is_not_deleted_even_if_manifest_hash_matches(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "demo:support.toml"
    stripped = "".join(target.read_text().splitlines(True)[2:])
    target.write_text(stripped)
    data = manifest(ws)
    for entry in data["agents"]:
        if entry["file"] == target.name:
            entry["sha256"] = ca.sha256_hex(stripped.encode())
    (agents_dir(ws) / ca.MANIFEST_NAME).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (ws / "planets/demo/agents/support.md").unlink()
    assert run(ws, env, "publish").returncode == 3
    assert target.read_text() == stripped


def test_edited_managed_file_is_not_overwritten_on_update(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "demo:sales.toml"
    target.write_text(target.read_text() + "# mine\n")
    edited = target.read_bytes()
    write_agent(ws, "demo", "sales", contract("sales", "Changed description."))
    assert run(ws, env, "publish").returncode == 3
    assert target.read_bytes() == edited


def test_source_change_updates_file(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    write_agent(ws, "demo", "sales", contract("sales", "Changed description."))
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "update: demo:sales.toml" in proc.stdout
    parsed = tomllib.loads((agents_dir(ws) / "demo:sales.toml").read_text())
    assert parsed["description"] == "Changed description."


def test_user_deleted_managed_file_is_restored(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    (agents_dir(ws) / "demo:sales.toml").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "restore: demo:sales.toml" in proc.stdout
    assert "demo:sales.toml" in toml_files(ws)


@needs_unreadable
def test_unreadable_source_is_never_retired(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    source = ws / "planets/demo/agents/support.md"
    os.chmod(source, 0)
    try:
        proc = run(ws, env, "publish")
        assert proc.returncode == 0
        assert "demo:support.toml" in toml_files(ws)
        assert "source status unknown" in proc.stdout
    finally:
        os.chmod(source, 0o644)


def test_planets_dir_missing_with_manifest_entries_is_refused(ws, env, tmp_path):
    enable(ws, env)
    run(ws, env, "publish")
    moved = tmp_path / "planets-moved"
    (ws / "planets").rename(moved)
    before = snapshot(agents_dir(ws))
    assert run(ws, env, "publish").returncode == 5
    assert snapshot(agents_dir(ws)) == before


# --------------------------------------------------------------------------
# Manifest manipulation
# --------------------------------------------------------------------------

def published(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    return agents_dir(ws) / ca.MANIFEST_NAME


def test_corrupt_manifest_json_is_refused(ws, env):
    path = published(ws, env)
    path.write_text("{broken")
    before = snapshot(agents_dir(ws))
    assert run(ws, env, "publish").returncode == 5
    assert snapshot(agents_dir(ws)) == before


def mutate(path, fn):
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


MANIFEST_MUTATIONS = {
    "unknown_top_key": lambda d: d.update(extra=1),
    "bad_format": lambda d: d.update(format=3),
    "format1_with_new_name": lambda d: d.update(format=1),
    "bad_generator": lambda d: d.update(generator="other"),
    "unknown_entry_key": lambda d: d["agents"][0].update(extra=1),
    "missing_entry_key": lambda d: d["agents"][0].pop("sha256"),
    "path_traversal": lambda d: d["agents"][0].update(file="../../outside.toml"),
    "separator": lambda d: d["agents"][0].update(file="sub/demo:sales.toml"),
    "manual_name": lambda d: d["agents"][0].update(name="uh_sales", file="uh_sales.toml"),
    "short_hash": lambda d: d["agents"][0].update(sha256="abc"),
    "bad_identity": lambda d: d["agents"][0].update(identity="demo:other"),
    "bad_source": lambda d: d["agents"][0].update(source="../x.md"),
    "bad_retiring": lambda d: d["agents"][0].update(retiring=False),
    "duplicate_entry": lambda d: d["agents"].append(dict(d["agents"][0])),
    "agents_not_list": lambda d: d.update(agents={}),
}


@pytest.mark.parametrize("name", sorted(MANIFEST_MUTATIONS))
def test_invalid_manifest_is_refused_before_any_write(ws, env, name, tmp_path):
    path = published(ws, env)
    mutate(path, MANIFEST_MUTATIONS[name])
    (ws / "planets/demo/agents/extra.md").write_text(contract("extra"))
    (tmp_path / "outside.toml").write_text("keep")
    before = snapshot(ws)
    proc = run(ws, env, "publish")
    assert proc.returncode == 5, proc.stderr
    assert snapshot(ws) == before
    assert (tmp_path / "outside.toml").read_text() == "keep"


def test_entry_pointing_at_manual_file_is_never_touched(ws, env):
    path = published(ws, env)
    manual = agents_dir(ws) / "uh_sales.toml"
    manual.write_text('name = "uh_sales"\n')
    mutate(path, lambda d: d["agents"][0].update(
        name="uh_sales", file="uh_sales.toml", sha256=ca.sha256_hex(manual.read_bytes())))
    assert run(ws, env, "publish").returncode == 5
    assert manual.read_text() == 'name = "uh_sales"\n'


def test_solar_prefixed_manual_file_with_matching_hash_but_no_mark_is_kept(ws, env):
    path = published(ws, env)
    manual = agents_dir(ws) / "demo:support.toml"
    manual.write_text('name = "demo:support"\ndescription = "x"\ndeveloper_instructions = "y"\n')
    mutate(path, lambda d: [e.update(sha256=ca.sha256_hex(manual.read_bytes()))
                            for e in d["agents"] if e["file"] == manual.name])
    before = manual.read_bytes()
    (ws / "planets/demo/agents/support.md").unlink()
    assert run(ws, env, "publish").returncode == 3
    assert manual.read_bytes() == before


def test_hash_tampering_means_not_ours(ws, env):
    path = published(ws, env)
    mutate(path, lambda d: [e.update(sha256="0" * 64) for e in d["agents"] if e["file"] == "demo:sales.toml"])
    before = (agents_dir(ws) / "demo:sales.toml").read_bytes()
    write_agent(ws, "demo", "sales", contract("sales", "Changed."))
    assert run(ws, env, "publish").returncode == 3
    assert (agents_dir(ws) / "demo:sales.toml").read_bytes() == before


# --------------------------------------------------------------------------
# Failure, recovery, concurrency, idempotence
# --------------------------------------------------------------------------

def assert_converged(ws, env):
    proc = run(ws, env, "preview", "--contents", "--json")
    data = json.loads(proc.stdout)
    assert {i["action"] for i in data["items"]} <= {"keep"}, data
    entries = manifest(ws)["agents"]
    assert all("previous_sha256" not in e and "retiring" not in e for e in entries)
    for entry in entries:
        assert ca.sha256_hex((agents_dir(ws) / entry["file"]).read_bytes()) == entry["sha256"]


@pytest.mark.parametrize("fail_after", [0, 1, 2, 3, 4])
def test_partial_failure_converges_on_next_run(ws, env, fail_after):
    enable(ws, env)
    proc = run(ws, env, "publish", extra_env={"SOLAR_CODEX_AGENTS_TEST_FAIL_AFTER": str(fail_after)})
    assert proc.returncode != 0
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert toml_files(ws) == ["demo:sales.toml", "demo:support.toml", "other:ops.toml"]
    assert_converged(ws, env)
    assert not [p for p in agents_dir(ws).iterdir() if p.name.startswith(ca.TMP_PREFIX)]


def test_recovery_preserves_user_edited_file_and_retires_cleanly(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    sales = agents_dir(ws) / "demo:sales.toml"
    sales.write_text(sales.read_text() + "# user\n")
    edited = sales.read_bytes()
    write_agent(ws, "demo", "support", contract("support", "Changed."))
    write_agent(ws, "demo", "newone", contract("newone"))
    (ws / "planets/other/agents/ops.md").unlink()
    proc = run(ws, env, "publish", extra_env={"SOLAR_CODEX_AGENTS_TEST_FAIL_AFTER": "2"})
    assert proc.returncode != 0
    proc = run(ws, env, "publish")
    assert proc.returncode == 3  # the edited file is reported, everything else applied
    assert sales.read_bytes() == edited
    assert "other:ops.toml" not in toml_files(ws)
    assert "demo:newone.toml" in toml_files(ws)
    assert tomllib.loads((agents_dir(ws) / "demo:support.toml").read_text())["description"] == "Changed."
    assert run(ws, env, "publish").returncode == 3


def test_two_simultaneous_publishers_end_consistent(ws, env):
    enable(ws, env)
    for i in range(12):
        write_agent(ws, "demo", f"agent{i}", contract(f"agent{i}"))
    cmd = [sys.executable, str(SCRIPT), "--workspace", str(ws), "publish"]
    procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    codes = [p.wait(timeout=60) for p in procs]
    assert codes == [0, 0, 0]
    assert len(toml_files(ws)) == 15
    assert_converged(ws, env)
    before = snapshot(ws / ".codex")
    time.sleep(0.05)
    assert run(ws, env, "publish").returncode == 0
    assert snapshot(ws / ".codex") == before


def test_lock_held_means_exit_4_and_nothing_changes(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    write_agent(ws, "demo", "late", contract("late"))
    before = snapshot(ws / ".codex")
    fd = os.open(agents_dir(ws), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        proc = run(ws, env, "publish", extra_env={"SOLAR_CODEX_AGENTS_LOCK_TIMEOUT": "0.3"})
    finally:
        os.close(fd)
    assert proc.returncode == 4
    assert snapshot(ws / ".codex") == before
    assert run(ws, env, "publish").returncode == 0
    assert "demo:late.toml" in toml_files(ws)


def test_stale_temp_files_are_cleaned(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    stale = agents_dir(ws) / ".solar-tmp-999-1"
    stale.write_text("partial")
    assert run(ws, env, "publish").returncode == 0
    assert not stale.exists()


def test_second_run_is_a_byte_and_mtime_identical_noop(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    before = snapshot(ws)
    time.sleep(0.05)
    proc = run(ws, env, "publish")
    assert proc.returncode == 0
    assert snapshot(ws) == before
    assert all(line.startswith("keep:") for line in proc.stdout.splitlines() if line)


def test_codex_home_and_config_toml_are_untouched(ws, env):
    (ws / ".codex").mkdir()
    config = ws / ".codex/config.toml"
    config.write_text('model = "x"\n[agents]\nmax_threads = 2\n')
    before_config = config.read_bytes()
    home = Path(env["CODEX_HOME"])
    before_home = snapshot(home)
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    assert run(ws, env, "disable").returncode == 0
    assert config.read_bytes() == before_config
    assert snapshot(home) == before_home
    assert sorted(p.name for p in (ws / ".codex").iterdir()) == ["agents", "config.toml"]


def test_nothing_to_publish_creates_nothing(tmp_path, env):
    root = tmp_path / "empty"
    (root / "planets/demo/agents").mkdir(parents=True)
    write_settings(root)
    assert run(root, env, "enable").returncode == 0
    before = snapshot(root)
    proc = run(root, env, "publish")
    assert proc.returncode == 0
    assert snapshot(root) == before
    assert not (root / ".codex").exists()


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------

@pytest.mark.parametrize("args", [("preview",), ("preview", "--json"), ("preview", "--contents"),
                                  ("preview", "--contents", "--json"), ("status",), ("status", "--json"),
                                  ("exclude", "list")])
def test_preview_and_status_never_write(ws, env, args):
    assert not (ws / ".codex").exists()
    before = snapshot(ws)
    proc = run(ws, env, *args)
    assert proc.returncode in (0, 3)
    assert snapshot(ws) == before
    assert not (ws / ".codex").exists()


def test_preview_after_publish_never_writes(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    (agents_dir(ws) / ".solar-tmp-1").write_text("stale")
    (ws / "planets/demo/agents/support.md").unlink()
    before = snapshot(ws)
    proc = run(ws, env, "preview", "--contents")
    assert proc.returncode == 0 and "would retire: demo:support.toml" in proc.stdout
    assert snapshot(ws) == before


def test_scope_preview_lists_names_and_classification(ws, env):
    write_settings(ws, sync_exclude_planets=["other"])
    run(ws, env, "exclude", "add", PERSONAL)
    data = json.loads(run(ws, env, "preview", "--json").stdout)
    status = {p["name"]: p["status"] for p in data["planets"]}
    assert status == {"demo": "would read", "other": "excluded (global)", PERSONAL: "excluded (codex)"}
    assert data["mode"] == "scope" and data["enabled"] is False


def test_preview_contents_text_has_no_file_contents(ws, env):
    write_agent(ws, "demo", "private-ish", contract("private-ish", "A distinctive description phrase.", "Distinctive body phrase.\n"))
    out = run(ws, env, "preview", "--contents").stdout + run(ws, env, "publish").stdout
    assert "distinctive description" not in out.lower() and "distinctive body" not in out.lower()


def test_enable_prints_scope_before_writing(ws, env):
    run(ws, env, "exclude", "add", PERSONAL)
    proc = run(ws, env, "enable")
    lines = proc.stdout.splitlines()
    assert f"  {PERSONAL}: excluded (codex)" in lines
    assert lines.index(f"  {PERSONAL}: excluded (codex)") < [i for i, l in enumerate(lines) if l.startswith("OK:")][0]


def test_python_without_tomllib_refuses(ws, env, monkeypatch):
    monkeypatch.setattr(ca, "tomllib", None)
    with pytest.raises(ca.Refusal):
        ca.require_tomllib()


# --------------------------------------------------------------------------
# Migration from the format 1 scheme (solar__<planet>__<agent>)
# --------------------------------------------------------------------------

LEGACY_SET = [("demo", "sales"), ("demo", "support"), ("other", "ops")]


def legacy_file(planet, agent):
    return f"{ca.legacy_public_name(planet, agent)}.toml"


def write_legacy_publication(ws, targets=LEGACY_SET, with_manifest=True):
    """Synthesize what a format 1 publication left behind: solar__ files and a
    format 1 manifest. Files are rendered with the current renderer under the old
    name, which keeps the generation mark, the source line and the hash contract."""
    agents_dir(ws).mkdir(parents=True, exist_ok=True)
    entries = []
    for planet, agent in targets:
        raw = (ws / "planets" / planet / "agents" / f"{agent}.md").read_bytes()
        parsed = ca.parse_contract(planet, agent, raw)
        name = ca.legacy_public_name(planet, agent)
        text, _ = ca.render_agent(planet, agent, name, parsed.description, parsed.body, parsed.source_sha)
        (agents_dir(ws) / f"{name}.toml").write_text(text)
        entries.append({
            "source": f"planets/{planet}/agents/{agent}.md", "identity": f"{planet}:{agent}",
            "source_sha256": parsed.source_sha, "name": name, "file": f"{name}.toml",
            "sha256": ca.sha256_hex(text.encode()),
        })
    if with_manifest:
        doc = {"format": 1, "generator": ca.MANIFEST_GENERATOR, "agents": entries}
        (agents_dir(ws) / ca.MANIFEST_NAME).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


NEW_SET = ["demo:sales.toml", "demo:support.toml", "other:ops.toml"]
OLD_SET = sorted(legacy_file(p, a) for p, a in LEGACY_SET)


def test_legacy_manifest_is_read_by_the_validator():
    entries = [{"source": "planets/demo/agents/sales.md", "identity": "demo:sales",
                "source_sha256": "a" * 64, "name": "solar__demo__sales",
                "file": "solar__demo__sales.toml", "sha256": "b" * 64}]
    raw = json.dumps({"format": 1, "generator": ca.MANIFEST_GENERATOR, "agents": entries}).encode()
    assert ca.validate_manifest(raw)[0]["name"] == "solar__demo__sales"
    # A new-scheme name is not a format 1 name.
    new = [dict(entries[0], name="demo:sales", file="demo:sales.toml")]
    with pytest.raises(ca.Refusal):
        ca.validate_manifest(json.dumps({"format": 1, "generator": ca.MANIFEST_GENERATOR, "agents": new}).encode())
    # A format 2 manifest may list old and new entries of one source while a migration is in flight.
    both = entries + new
    assert len(ca.validate_manifest(json.dumps({"format": 2, "generator": ca.MANIFEST_GENERATOR, "agents": both}).encode())) == 2


def test_legacy_unchanged_files_migrate_in_one_run(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert toml_files(ws) == NEW_SET
    data = manifest(ws)
    assert data["format"] == 2 and [e["file"] for e in data["agents"]] == NEW_SET
    assert "retire: solar__demo__sales.toml" in proc.stdout and "(migrated to demo:sales)" in proc.stdout
    assert "add: demo:sales.toml" in proc.stdout
    for name in NEW_SET:
        assert tomllib.loads((agents_dir(ws) / name).read_text())["name"] == name[:-5]
    assert_converged(ws, env)
    # The second run changes nothing, not even mtimes.
    before = snapshot(ws)
    time.sleep(0.05)
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and snapshot(ws) == before
    assert all(line.startswith("keep:") for line in proc.stdout.splitlines() if line)


def test_legacy_preview_describes_migration_and_writes_nothing(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    before = snapshot(ws)
    proc = run(ws, env, "preview", "--contents")
    assert proc.returncode == 0
    assert "would add: demo:sales.toml" in proc.stdout
    assert "would retire: solar__demo__sales.toml" in proc.stdout
    assert snapshot(ws) == before


def test_legacy_edited_file_is_a_conflict_and_untouched(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    edited = agents_dir(ws) / legacy_file("demo", "sales")
    edited.write_text(edited.read_text() + "# my note\n")
    before = edited.read_bytes()
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert edited.read_bytes() == before
    assert "demo:sales.toml" not in toml_files(ws)
    assert "legacy file solar__demo__sales.toml was edited" in proc.stdout
    # The rest migrated.
    assert toml_files(ws) == sorted(["demo:support.toml", "other:ops.toml", edited.name])
    data = manifest(ws)
    assert data["format"] == 2 and edited.name in [e["file"] for e in data["agents"]]
    # Stable: the next run reports the same conflict and changes nothing.
    snap = snapshot(ws)
    time.sleep(0.05)
    assert run(ws, env, "publish").returncode == 3
    assert snapshot(ws) == snap
    # Once the user removes the edited file, the new role is published.
    edited.unlink()
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws) == NEW_SET
    assert [e["file"] for e in manifest(ws)["agents"]] == NEW_SET


@pytest.mark.parametrize("damage", ["mark_stripped", "name_changed"])
def test_legacy_file_is_retired_only_when_mark_name_and_hash_all_match(ws, env, damage):
    write_legacy_publication(ws)
    enable(ws, env)
    target = agents_dir(ws) / legacy_file("demo", "sales")
    text = target.read_text()
    if damage == "mark_stripped":
        text = "".join(text.splitlines(True)[2:])
    else:
        text = text.replace('name = "solar__demo__sales"', 'name = "solar__demo__renamed"')
    target.write_text(text)
    # Make the manifest hash match, so only the mark / name guard can protect the file.
    path = agents_dir(ws) / ca.MANIFEST_NAME
    mutate(path, lambda d: [e.update(sha256=ca.sha256_hex(text.encode()))
                            for e in d["agents"] if e["file"] == target.name])
    assert run(ws, env, "publish").returncode == 3
    assert target.read_text() == text
    assert "demo:sales.toml" not in toml_files(ws)


def test_legacy_files_without_manifest_are_never_ours(ws, env):
    write_legacy_publication(ws, with_manifest=False)
    handmade = agents_dir(ws) / "solar__demo__handmade.toml"
    handmade.write_text('name = "solar__demo__handmade"\ndescription = "mine"\ndeveloper_instructions = "x"\n')
    before = {p.name: p.read_bytes() for p in agents_dir(ws).glob("*.toml")}
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert "references this contract" in proc.stdout
    assert {p.name: p.read_bytes() for p in agents_dir(ws).glob("*.toml")} == before
    assert not (agents_dir(ws) / ca.MANIFEST_NAME).exists()
    # Even when the contracts disappear nothing with the solar__ prefix is deleted.
    for planet, agent in LEGACY_SET:
        (ws / "planets" / planet / "agents" / f"{agent}.md").unlink()
    assert run(ws, env, "publish").returncode == 0
    assert {p.name: p.read_bytes() for p in agents_dir(ws).glob("*.toml")} == before


def test_legacy_entry_whose_contract_is_gone_is_retired(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    (ws / "planets/demo/agents/support.md").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 0
    assert toml_files(ws) == ["demo:sales.toml", "other:ops.toml"]
    assert "retire: solar__demo__support.toml" in proc.stdout


def test_legacy_file_already_deleted_by_the_user_is_just_dropped(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    (agents_dir(ws) / legacy_file("demo", "sales")).unlink()
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws) == NEW_SET
    assert_converged(ws, env)


def test_legacy_new_target_conflict_keeps_the_old_role(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    (agents_dir(ws) / "demo:sales.toml").write_text("unmanaged\n")
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert (agents_dir(ws) / "demo:sales.toml").read_text() == "unmanaged\n"
    assert (agents_dir(ws) / legacy_file("demo", "sales")).is_file()
    assert "demo:support.toml" in toml_files(ws) and legacy_file("demo", "support") not in toml_files(ws)


FAIL_POINTS = list(range(0, 8))  # 1 transitional manifest + 3 writes + 3 deletes + 1 final manifest


@pytest.mark.parametrize("fail_after", FAIL_POINTS)
def test_legacy_partial_failure_never_loses_a_role_and_resumes(ws, env, fail_after):
    write_legacy_publication(ws)
    enable(ws, env)
    proc = run(ws, env, "publish", extra_env={"SOLAR_CODEX_AGENTS_TEST_FAIL_AFTER": str(fail_after)})
    assert proc.returncode != 0
    present = set(toml_files(ws))
    for planet, agent in LEGACY_SET:
        assert {legacy_file(planet, agent), f"{planet}:{agent}.toml"} & present, (planet, agent)
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert toml_files(ws) == NEW_SET
    assert manifest(ws)["format"] == 2
    assert_converged(ws, env)
    assert not [p for p in agents_dir(ws).iterdir() if p.name.startswith(ca.TMP_PREFIX)]
    before = snapshot(ws)
    time.sleep(0.05)
    assert run(ws, env, "publish").returncode == 0 and snapshot(ws) == before


def test_legacy_partial_failure_with_an_edited_file_still_converges(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    edited = agents_dir(ws) / legacy_file("other", "ops")
    edited.write_text(edited.read_text() + "# mine\n")
    kept = edited.read_bytes()
    assert run(ws, env, "publish", extra_env={"SOLAR_CODEX_AGENTS_TEST_FAIL_AFTER": "3"}).returncode != 0
    assert run(ws, env, "publish").returncode == 3
    assert edited.read_bytes() == kept
    assert "other:ops.toml" not in toml_files(ws)
    assert {"demo:sales.toml", "demo:support.toml"} <= set(toml_files(ws))


def test_legacy_entry_of_excluded_planet_is_retired_without_reading_the_planet(ws, env, tmp_path):
    write_legacy_publication(ws, LEGACY_SET + [(PERSONAL, "diary")])
    assert run(ws, env, "exclude", "add", PERSONAL).returncode == 0
    assert run(ws, env, "enable").returncode == 0
    proc, seen = audited(ws, env, tmp_path, "publish")
    assert proc.returncode == 0, proc.stderr
    assert not touched_planet(seen, PERSONAL), seen
    assert toml_files(ws) == NEW_SET


def test_excluded_planet_with_synthetic_personal_planet_is_never_listed_or_opened(ws, env, tmp_path):
    write_agent(ws, "personal", "journal", contract("journal", "Private synthetic role."))
    (ws / "planets/personal/agents/notes.md").write_text(contract("notes", body="Read planets/personal/secret.md\n"))
    write_agent(ws, "demo", "peek", contract("peek", body="Ask personal:journal about it\n"))
    assert run(ws, env, "exclude", "add", "personal").returncode == 0
    assert run(ws, env, "enable").returncode == 0
    for args in (("publish",), ("preview", "--contents"), ("preview",), ("status",)):
        proc, seen = audited(ws, env, tmp_path, *args)
        assert proc.returncode == 0, proc.stderr
        assert not touched_planet(seen, "personal"), (args, seen)
    assert not [n for n in toml_files(ws) if n.startswith("personal:") or n == "demo:peek.toml"]
    assert omitted(preview_json(ws, env))["planets/demo/agents/peek.md"] == "references excluded planet personal"


def test_manual_agent_is_intact_and_its_contract_identity_is_protected(tmp_path, env):
    root = tmp_path / "ws"
    root.mkdir()
    write_settings(root)
    write_agent(root, "uhorizon", "uh-sales", contract("uh-sales"))
    write_agent(root, "uhorizon", "uh-backend-dev", contract("uh-backend-dev"))
    agents_dir(root).mkdir(parents=True)
    manual = agents_dir(root) / "uh_sales.toml"
    manual.write_text('name = "uh_sales"\ndescription = "Manual"\n'
                      'developer_instructions = "Read planets/uhorizon/agents/uh-sales.md"\n')
    digest = ca.sha256_hex(manual.read_bytes())
    assert run(root, env, "enable").returncode == 0
    proc = run(root, env, "publish")
    assert proc.returncode == 3 and "references this contract" in proc.stdout
    assert ca.sha256_hex(manual.read_bytes()) == digest
    assert "uhorizon:uh-sales.toml" not in toml_files(root)
    assert "uhorizon:uh-backend-dev.toml" in toml_files(root)
    # Excluding the identity makes it a clean omission and still leaves the manual file alone.
    assert run(root, env, "exclude", "add", "uhorizon:uh-sales").returncode == 0
    proc = run(root, env, "publish")
    assert proc.returncode == 0, proc.stdout
    assert omitted(preview_json(root, env))["planets/uhorizon/agents/uh-sales.md"] == "excluded by identity"
    assert ca.sha256_hex(manual.read_bytes()) == digest
    assert "uhorizon:uh-sales.toml" not in toml_files(root)


def test_identity_exclusion_retires_a_published_new_scheme_role(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    assert "demo:sales.toml" in toml_files(ws)
    assert run(ws, env, "exclude", "add", "DEMO:Sales").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    assert "demo:sales.toml" not in toml_files(ws) and "demo:support.toml" in toml_files(ws)


def test_wrapper_and_messages_use_the_new_names(ws, env):
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert "add: demo:sales.toml <- planets/demo/agents/sales.md" in proc.stdout
    assert "solar__" not in proc.stdout
    text = (agents_dir(ws) / "demo:sales.toml").read_text()
    assert "solar__" not in text
    assert "identity: demo:sales " in text


def test_template_files_are_skipped_and_leading_underscore_names_are_rejected(ws, env):
    """`_lead.md` is a template by convention: never published, and not a valid name."""
    enable(ws, env)
    write_agent(ws, "demo", "_lead", contract("_lead"))
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws) == ["demo:sales.toml", "demo:support.toml", "other:ops.toml"]
    with pytest.raises(ca.ContractError):
        ca.canonical_identity("demo", "_lead")


def test_maximum_length_names_publish_and_round_trip(ws, env):
    enable(ws, env)
    planet, agent = "p" * ca.MAX_COMPONENT_LEN, "a" * ca.MAX_COMPONENT_LEN
    write_agent(ws, planet, agent, contract(agent))
    assert run(ws, env, "publish").returncode == 0
    name = f"{planet}:{agent}"
    assert len(name) == 2 * ca.MAX_COMPONENT_LEN + 1
    assert (agents_dir(ws) / f"{name}.toml").is_file()
    entry = [e for e in manifest(ws)["agents"] if e["name"] == name][0]
    assert entry["file"] == f"{name}.toml" and entry["identity"] == name
    assert tomllib.loads((agents_dir(ws) / entry["file"]).read_text())["name"] == name
    assert_converged(ws, env)


def test_identity_exclusion_is_deliberately_wider_than_published_names(ws, env):
    """Published names keep `-` and `_` apart; exclusions still treat them as equal
    (the privacy-safe direction), so excluding uh-sales also excludes uh_sales."""
    enable(ws, env)
    write_agent(ws, "demo", "uh-sales", contract("uh-sales"))
    write_agent(ws, "demo", "uh_sales", contract("uh_sales"))
    assert run(ws, env, "exclude", "add", "demo:uh-sales").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    files = toml_files(ws)
    assert "demo:uh-sales.toml" not in files and "demo:uh_sales.toml" not in files
    reasons = omitted(preview_json(ws, env))
    assert reasons["planets/demo/agents/uh-sales.md"] == "excluded by identity"
    assert reasons["planets/demo/agents/uh_sales.md"] == "excluded by identity"


def test_published_name_is_the_exclusion_identity_and_the_documented_form(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    for entry in manifest(ws)["agents"]:
        assert run(ws, env, "exclude", "add", entry["name"]).returncode == 0  # same string
    assert run(ws, env, "publish").returncode == 0
    assert toml_files(ws) == []
    docs = [CORE / "skills/solar-client/references/codex-agents.md",
            CORE / "skills/solar-client/SKILL.md",
            CORE / "skills/solar-agent-creator/SKILL.md"]
    for doc in docs:
        text = doc.read_text()
        assert "<planet>:<agent>" in text, doc
    agent_doc = docs[2].read_text()
    assert f"{ca.MAX_COMPONENT_LEN} characters" in agent_doc and "[A-Za-z0-9._-]" in agent_doc
    assert f"{ca.MAX_COMPONENT_LEN} characters" in docs[0].read_text()


def test_plan_items_have_one_shape_for_every_action(ws, env):
    write_legacy_publication(ws)
    enable(ws, env)
    (ws / "planets/demo/agents/support.md").unlink()
    data = preview_json(ws, env)
    assert {item["action"] for item in data["items"]} >= {"add", "retire"}
    assert all(set(item) == {"action", "file", "source", "identity", "reason"} for item in data["items"])
    assert [i["reason"] for i in data["items"] if i["file"] == legacy_file("demo", "sales")] == [
        "migrated to demo:sales"]
    assert all(i["reason"] is None for i in data["items"] if i["action"] == "add")


FIXTURE = Path(__file__).parent / "fixtures/codex_agents_v0_43_0"


def install_v043_fixture(ws):
    """Real output of Solar v0.43.0 (see the fixture README), placed in `ws`."""
    for contract_file in sorted((FIXTURE / "contracts").glob("*/*.md")):
        folder = ws / "planets" / contract_file.parent.name / "agents"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / contract_file.name).write_bytes(contract_file.read_bytes())
    agents_dir(ws).mkdir(parents=True, exist_ok=True)
    for published in sorted((FIXTURE / "published").iterdir()):
        target = ".solar-managed.json" if published.name == "solar-managed.json" else published.name
        (agents_dir(ws) / target).write_bytes(published.read_bytes())


def test_real_v0_43_0_output_migrates_without_conflict(ws, env):
    install_v043_fixture(ws)
    old_files = sorted(p.name for p in agents_dir(ws).glob("solar__*.toml"))
    assert old_files == ["solar__louis__lou_ai.toml", "solar__uhorizon__uh_backend_dev.toml"]
    assert json.loads((agents_dir(ws) / ca.MANIFEST_NAME).read_text())["format"] == 1
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "conflict:" not in proc.stdout
    assert [n for n in toml_files(ws) if n.startswith("solar__")] == []
    assert "uhorizon:uh-backend-dev.toml" in toml_files(ws) and "louis:lou-ai.toml" in toml_files(ws)
    assert manifest(ws)["format"] == 2
    parsed = tomllib.loads((agents_dir(ws) / "uhorizon:uh-backend-dev.toml").read_text())
    assert parsed["name"] == "uhorizon:uh-backend-dev"
    assert "Synthetic body" in parsed["developer_instructions"]
    assert_converged(ws, env)
    before = snapshot(ws)
    time.sleep(0.05)
    assert run(ws, env, "publish").returncode == 0 and snapshot(ws) == before
