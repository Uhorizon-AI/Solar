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
    tricky = tomllib.loads((agents_dir(ws) / "solar__demo__tricky.toml").read_text())
    assert tricky["description"] == 'Quotes "here" and \\ slashes'
    assert 'Body with """ triple\nand a trailing quote "\n' in tricky["developer_instructions"]
    assert "does not grant" not in tricky["developer_instructions"]
    assert "grants no authority" in tricky["developer_instructions"]
    assert "planets/demo/agents/tricky.md" in tricky["developer_instructions"]


def test_body_crlf_is_normalized_to_lf(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "crlf", raw=b"---\r\nname: crlf\r\ndescription: Windows line endings\r\n---\r\n\r\nline one\r\nline two\r\n")
    assert run(ws, env, "publish").returncode == 0
    text = tomllib.loads((agents_dir(ws) / "solar__demo__crlf.toml").read_text())["developer_instructions"]
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
    "badchars": (b"---\nname: 'bad name'\ndescription: x\n---\nbody\n", "unsupported characters"),
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
    assert "solar__demo__sales.toml" in actions(data)


def test_valid_scalar_forms(ws, env):
    write_agent(ws, "demo", "folded", "---\nname: folded\ndescription: >\n  First part\n  second part.\n---\nbody\n")
    write_agent(ws, "demo", "literal", "---\nname: literal\ndescription: |\n  First\n  second\n---\nbody\n")
    write_agent(ws, "demo", "dq", '---\nname: "dq"\ndescription: "Quoted \\"x\\" here"\n---\nbody\n')
    write_agent(ws, "demo", "sq", "---\nname: 'sq'\ndescription: 'It''s fine'\ntools: [a, b]\n---\nbody\n")
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    desc = lambda n: tomllib.loads((agents_dir(ws) / f"solar__demo__{n}.toml").read_text())["description"]
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
    assert toml_files(ws) == ["solar__demo__sales.toml", "solar__demo__support.toml", "solar__other__ops.toml"]
    out = run(ws, env, "publish").stdout
    assert "nested" not in out and "README" not in out and "hidden" not in out


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def test_name_normalization(ws, env):
    write_agent(ws, "demo", "Sales-Lead_2", contract("Sales-Lead_2"))
    data = preview_json(ws, env)
    assert actions(data)["solar__demo__sales_lead_2.toml"] == "add"


@pytest.mark.parametrize("planet,agent,why", [
    ("demo", "a--b", "public agent name"),
    ("demo", "a__b", "public agent name"),
    ("demo", "trail_", "public agent name"),
    ("my.planet", "a", "public agent name"),
    ("demo", "x" * 100, "96"),
])
def test_unrepresentable_names_are_omitted(ws, env, planet, agent, why):
    write_agent(ws, planet, agent, contract(agent))
    data = preview_json(ws, env)
    source = f"planets/{planet}/agents/{agent}.md"
    assert why in omitted(data)[source]


# --------------------------------------------------------------------------
# Collisions and ownership
# --------------------------------------------------------------------------

def test_hyphen_underscore_pair_collide(ws, env):
    enable(ws, env)
    write_agent(ws, "demo", "a-b", contract("a-b"))
    write_agent(ws, "demo", "a_b", contract("a_b"))
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert "solar__demo__a_b.toml" not in toml_files(ws)
    assert proc.stdout.count("conflict:") == 2
    assert "solar__demo__sales.toml" in toml_files(ws)


def test_planet_normalization_collision(ws, env):
    enable(ws, env)
    write_agent(ws, "a-b", "c", contract("c"))
    write_agent(ws, "a_b", "c", contract("c"))
    assert run(ws, env, "publish").returncode == 3
    assert "solar__a_b__c.toml" not in toml_files(ws)


def test_case_variant_foreign_file_blocks(ws, env):
    agents_dir(ws).mkdir(parents=True)
    foreign = agents_dir(ws) / "SOLAR__demo__sales.toml"
    foreign.write_text('name = "SOLAR__demo__sales"\ndescription = "m"\ndeveloper_instructions = "x"\n')
    before = foreign.read_bytes()
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert foreign.read_bytes() == before
    assert "solar__demo__sales.toml" not in os.listdir(agents_dir(ws))
    assert "planets/demo/agents/sales.md" in conflicts(preview_json(ws, env))


def test_foreign_toml_with_same_name_blocks(ws, env):
    agents_dir(ws).mkdir(parents=True)
    foreign = agents_dir(ws) / "mine.toml"
    foreign.write_text('name = "solar__demo__sales"\ndescription = "m"\ndeveloper_instructions = "x"\n')
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 3
    assert "solar__demo__sales.toml" not in toml_files(ws)
    assert "solar__demo__support.toml" in toml_files(ws)


def test_config_toml_agent_table_blocks_and_is_untouched(ws, env):
    (ws / ".codex").mkdir()
    config = ws / ".codex/config.toml"
    config.write_text('[agents.solar__demo__sales]\ndescription = "x"\n[agents]\nmax_threads = 3\n')
    before = config.read_bytes()
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 3
    assert "solar__demo__sales.toml" not in toml_files(ws)
    assert "solar__demo__support.toml" in toml_files(ws)
    assert config.read_bytes() == before


@pytest.mark.parametrize("kind", ["dir", "symlink", "file"])
def test_target_path_not_ours_is_a_conflict(ws, env, kind, tmp_path):
    agents_dir(ws).mkdir(parents=True)
    target = agents_dir(ws) / "solar__demo__sales.toml"
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
    assert "solar__demo__support.toml" in toml_files(ws)


def test_unmanaged_file_with_generation_mark_is_not_adopted(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    (agents_dir(ws) / ca.MANIFEST_NAME).unlink()
    before = (agents_dir(ws) / "solar__demo__sales.toml").read_bytes()
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert "generation mark" in proc.stdout
    assert (agents_dir(ws) / "solar__demo__sales.toml").read_bytes() == before


def test_foreign_toml_referencing_contract_blocks_that_agent(ws, env):
    agents_dir(ws).mkdir(parents=True)
    manual = agents_dir(ws) / "manual_sales.toml"
    manual.write_text('name = "manual_sales"\ndescription = "m"\ndeveloper_instructions = "Read planets/demo/agents/sales.md first"\n')
    enable(ws, env)
    proc = run(ws, env, "publish")
    assert proc.returncode == 3
    assert "solar__demo__sales.toml" not in toml_files(ws)
    assert "solar__demo__support.toml" in toml_files(ws)
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
    assert "solar__demo__sales.toml" not in toml_files(ws)
    assert "solar__demo__support.toml" in toml_files(ws)
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
    assert "solar__personal_x__diary.toml" not in files
    if mode == "mixed":
        assert "solar__other__ops.toml" not in files
    else:
        assert "solar__other__ops.toml" in files
    assert PERSONAL.replace("-", "_") not in json.dumps(manifest(ws))


def test_planet_exclusion_is_case_insensitive(ws, env):
    write_settings(ws, sync_exclude_planets=["PERSONAL-X"])
    assert run(ws, env, "enable").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    assert "solar__personal_x__diary.toml" not in toml_files(ws)


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
    assert "solar__demo__ref_near.toml" in actions(data)


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
    assert not [s for s in seen if PERSONAL in s[1]], seen
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
        assert "solar__demo__sales.toml" in toml_files(ws)
    finally:
        os.chmod(planet, 0o755)


def test_disabled_by_default_reads_nothing(ws, env, tmp_path):
    proc, seen = audited(ws, env, tmp_path, "publish")
    assert proc.returncode == 0
    assert "disabled" in proc.stdout
    assert not (ws / ".codex").exists()
    assert not [s for s in seen if "/planets" in s[1] or ".codex" in s[1]], seen


def test_disabled_publish_with_nonexistent_planets_dir(tmp_path, env):
    root = tmp_path / "bare"
    (root / ".solar").mkdir(parents=True)
    assert run(root, env, "publish").returncode == 0
    assert not (root / ".codex").exists()


def test_retire_when_source_planet_excluded_later_never_reads_it(ws, env, tmp_path):
    assert run(ws, env, "enable").returncode == 0
    assert run(ws, env, "publish").returncode == 0
    assert "solar__personal_x__diary.toml" in toml_files(ws)
    run(ws, env, "exclude", "add", PERSONAL)
    proc, seen = audited(ws, env, tmp_path, "publish")
    assert proc.returncode == 0, proc.stderr
    assert "solar__personal_x__diary.toml" not in toml_files(ws)
    assert not [s for s in seen if PERSONAL in s[1]], seen
    assert "retire: solar__personal_x__diary.toml" in proc.stdout


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
    assert proc.returncode == 0 and "retire: solar__demo__support.toml" in proc.stdout
    assert "solar__demo__support.toml" not in toml_files(ws)
    assert [e["file"] for e in manifest(ws)["agents"]] == ["solar__demo__sales.toml", "solar__other__ops.toml"]


def test_invalid_contract_keeps_published_file(ws, env):
    """Editing a contract into an invalid state must not delete the role."""
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "solar__demo__support.toml"
    before = target.read_bytes()
    (ws / "planets/demo/agents/support.md").write_text("no frontmatter now\n")
    proc = run(ws, env, "publish")
    assert proc.returncode == 0
    assert "solar__demo__support.toml" in toml_files(ws)
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
    assert "solar__demo__support.toml" in toml_files(ws)


def test_removing_invalid_contract_then_retires(ws, env):
    """Once the invalid .md disappears, the kept file is finally retired."""
    enable(ws, env)
    run(ws, env, "publish")
    (ws / "planets/demo/agents/support.md").write_text("no frontmatter now\n")
    assert run(ws, env, "publish").returncode == 0
    assert "solar__demo__support.toml" in toml_files(ws)
    (ws / "planets/demo/agents/support.md").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "retire: solar__demo__support.toml" in proc.stdout
    assert "solar__demo__support.toml" not in toml_files(ws)


def test_invalid_contract_then_excluded_retires(ws, env):
    """An invalid contract whose planet is later excluded is retired, not kept."""
    enable(ws, env)
    run(ws, env, "publish")
    (ws / "planets/demo/agents/support.md").write_text("no frontmatter now\n")
    assert run(ws, env, "publish").returncode == 0
    assert run(ws, env, "exclude", "add", "demo").returncode == 0
    proc = run(ws, env, "publish")
    assert proc.returncode == 0
    assert "solar__demo__support.toml" not in toml_files(ws)
    assert "solar__demo__sales.toml" not in toml_files(ws)


def test_user_edited_file_is_kept_and_reported_on_retire(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "solar__demo__support.toml"
    target.write_text(target.read_text() + "# user note\n")
    (ws / "planets/demo/agents/support.md").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 3 and "cannot retire" in proc.stdout
    assert target.exists() and "# user note" in target.read_text()
    assert "solar__demo__support.toml" in [e["file"] for e in manifest(ws)["agents"]]


def test_mark_stripped_file_is_not_deleted_even_if_manifest_hash_matches(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    target = agents_dir(ws) / "solar__demo__support.toml"
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
    target = agents_dir(ws) / "solar__demo__sales.toml"
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
    assert proc.returncode == 0 and "update: solar__demo__sales.toml" in proc.stdout
    parsed = tomllib.loads((agents_dir(ws) / "solar__demo__sales.toml").read_text())
    assert parsed["description"] == "Changed description."


def test_user_deleted_managed_file_is_restored(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    (agents_dir(ws) / "solar__demo__sales.toml").unlink()
    proc = run(ws, env, "publish")
    assert proc.returncode == 0 and "restore: solar__demo__sales.toml" in proc.stdout
    assert "solar__demo__sales.toml" in toml_files(ws)


def test_unreadable_source_is_never_retired(ws, env):
    enable(ws, env)
    run(ws, env, "publish")
    source = ws / "planets/demo/agents/support.md"
    os.chmod(source, 0)
    try:
        proc = run(ws, env, "publish")
        assert proc.returncode == 0
        assert "solar__demo__support.toml" in toml_files(ws)
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
    "bad_format": lambda d: d.update(format=2),
    "bad_generator": lambda d: d.update(generator="other"),
    "unknown_entry_key": lambda d: d["agents"][0].update(extra=1),
    "missing_entry_key": lambda d: d["agents"][0].pop("sha256"),
    "path_traversal": lambda d: d["agents"][0].update(file="../../outside.toml"),
    "separator": lambda d: d["agents"][0].update(file="sub/solar__demo__sales.toml"),
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
    manual = agents_dir(ws) / "solar__demo__support.toml"
    manual.write_text('name = "solar__demo__support"\ndescription = "x"\ndeveloper_instructions = "y"\n')
    mutate(path, lambda d: [e.update(sha256=ca.sha256_hex(manual.read_bytes()))
                            for e in d["agents"] if e["file"] == manual.name])
    before = manual.read_bytes()
    (ws / "planets/demo/agents/support.md").unlink()
    assert run(ws, env, "publish").returncode == 3
    assert manual.read_bytes() == before


def test_hash_tampering_means_not_ours(ws, env):
    path = published(ws, env)
    mutate(path, lambda d: [e.update(sha256="0" * 64) for e in d["agents"] if e["file"] == "solar__demo__sales.toml"])
    before = (agents_dir(ws) / "solar__demo__sales.toml").read_bytes()
    write_agent(ws, "demo", "sales", contract("sales", "Changed."))
    assert run(ws, env, "publish").returncode == 3
    assert (agents_dir(ws) / "solar__demo__sales.toml").read_bytes() == before


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
    assert toml_files(ws) == ["solar__demo__sales.toml", "solar__demo__support.toml", "solar__other__ops.toml"]
    assert_converged(ws, env)
    assert not [p for p in agents_dir(ws).iterdir() if p.name.startswith(ca.TMP_PREFIX)]


def test_recovery_preserves_user_edited_file_and_retires_cleanly(ws, env):
    enable(ws, env)
    assert run(ws, env, "publish").returncode == 0
    sales = agents_dir(ws) / "solar__demo__sales.toml"
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
    assert "solar__other__ops.toml" not in toml_files(ws)
    assert "solar__demo__newone.toml" in toml_files(ws)
    assert tomllib.loads((agents_dir(ws) / "solar__demo__support.toml").read_text())["description"] == "Changed."
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
    assert "solar__demo__late.toml" in toml_files(ws)


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
    assert proc.returncode == 0 and "would retire: solar__demo__support.toml" in proc.stdout
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
