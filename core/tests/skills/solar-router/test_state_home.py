"""State home grant (issue #175): table, launch commands, resolver and router scope.

No real client is started. The real-sandbox check (a task writes in its home and is denied
outside it) is manual: see core/docs/state-homes.md, "Manual verification".
"""
import json
import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

import router
from providers import PROVIDERS
from providers.base import STATE_HOME_GRANTS, StateHomeError
from state_home import resolve_state_home, skill_declares_state_home

GRANTED = ["claude", "codex", "agent", "agy"]


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "app-data" / "Solar" / "planets" / "p" / "watch"
    path.mkdir(parents=True)
    return path


@pytest.fixture(autouse=True)
def clean_providers():
    yield
    for provider in PROVIDERS.values():
        provider.state_home = None


def argv(name, prompt="do it"):
    with patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"):
        return PROVIDERS[name].get_cmd(prompt)


# --- the grant table --------------------------------------------------------

def test_table_has_exactly_the_four_verified_clients():
    assert sorted(STATE_HOME_GRANTS) == sorted(GRANTED)
    assert all(g.flag == "--add-dir" for g in STATE_HOME_GRANTS.values())


@pytest.mark.parametrize("name", GRANTED)
def test_no_state_home_leaves_the_command_unchanged(name):
    before = argv(name)
    PROVIDERS[name].state_home = None
    assert argv(name) == before
    # only agy carries a workspace --add-dir of its own; nobody gets a second one
    assert before.count("--add-dir") == (1 if name == "agy" else 0)


@pytest.mark.parametrize("name", GRANTED)
def test_grant_adds_only_the_state_home(name, home):
    baseline = argv(name)
    PROVIDERS[name].state_home = str(home)
    granted = argv(name)
    assert granted.count("--add-dir") == baseline.count("--add-dir") + 1
    # the only new path is the skill folder: no parent, no sibling
    new_paths = [a for a in granted if a.startswith("/") and a not in baseline]
    assert new_paths == [str(home)]


def test_claude_puts_the_prompt_before_the_variadic_option(home):
    PROVIDERS["claude"].state_home = str(home)
    cmd = argv("claude", "PROMPT")
    assert cmd[-3:] == ["PROMPT", "--add-dir", str(home)]


def test_codex_grant_stays_before_the_separator(home):
    PROVIDERS["codex"].state_home = str(home)
    cmd = argv("codex", "PROMPT")
    sep = cmd.index("--")
    assert cmd.index("--add-dir") < sep and cmd[sep + 1:] == ["PROMPT"]


def test_agent_and_agy_keep_the_prompt_last(home):
    PROVIDERS["agent"].state_home = str(home)
    assert argv("agent", "PROMPT")[-3:] == ["--add-dir", str(home), "PROMPT"]
    PROVIDERS["agy"].state_home = str(home)
    assert argv("agy", "PROMPT")[-4:] == ["--add-dir", str(home), "--print", "PROMPT"]


def test_env_override_still_receives_the_grant(home, monkeypatch):
    monkeypatch.setenv("SOLAR_ROUTER_CODEX_CMD", "mycodex exec --")
    PROVIDERS["codex"].state_home = str(home)
    assert argv("codex", "P")[1:] == ["exec", "--add-dir", str(home), "--", "P"]


def test_ollama_refuses_a_state_home(home):
    PROVIDERS["ollama"].state_home = str(home)
    with pytest.raises(StateHomeError) as err:
        PROVIDERS["ollama"].run("hi")
    assert err.value.code == "state_home_unsupported_provider"


@pytest.mark.parametrize("bad", ["relative/dir", "/does/not/exist"])
def test_missing_or_relative_home_is_an_error_not_a_fallback(bad):
    PROVIDERS["claude"].state_home = bad
    with pytest.raises(StateHomeError) as err:
        argv("claude")
    assert err.value.code == "state_home_unavailable"


# --- the resolver -----------------------------------------------------------

def make_skill(workspace, planet="p", skill="watch", declared="true"):
    d = workspace / "planets" / planet / "skills" / skill
    d.mkdir(parents=True)
    front = f"state_home: {declared}\n" if declared is not None else ""
    (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: x\n{front}---\nbody\n")
    return d


def test_resolver_creates_the_official_home(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    got = resolve_state_home(ws, "p", "watch")
    app = pathlib.Path(os.environ["SOLAR_APP_DATA"]).resolve()
    assert got.is_dir() and got.name == "watch" and got.parent.parent == app / "Solar" / "planets"


def test_resolver_requires_the_skill_to_opt_in(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws, declared=None)
    with pytest.raises(StateHomeError) as err:
        resolve_state_home(ws, "p", "watch")
    assert err.value.code == "state_home_not_declared"
    assert not skill_declares_state_home(ws / "planets/p/skills/watch/SKILL.md")


def test_resolver_false_is_not_opt_in(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws, declared="false")
    with pytest.raises(StateHomeError):
        resolve_state_home(ws, "p", "watch")


@pytest.mark.parametrize("planet,skill", [("p", "../other"), ("p", "a/b"), ("..", "watch"), ("p", ""), ("nope", "watch")])
def test_resolver_never_leaves_the_skill_folder(tmp_path, planet, skill):
    ws = tmp_path / "workspace"
    make_skill(ws)
    with pytest.raises(StateHomeError) as err:
        resolve_state_home(ws, planet, skill)
    assert err.value.code == "state_home_invalid"


def test_resolver_fails_clearly_when_the_home_cannot_be_created(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    with patch("solar_runtime.planet_state_dir", side_effect=PermissionError("denied")):
        with pytest.raises(StateHomeError) as err:
            resolve_state_home(ws, "p", "watch")
    assert err.value.code == "state_home_unavailable" and "denied" in str(err.value)


# --- the router scope -------------------------------------------------------

def test_router_scopes_the_grant_to_one_request(home):
    seen = {}

    def fake_run(prompt, **_):
        seen["during"] = PROVIDERS["claude"].state_home
        return "ok"

    payload = dict(request_id="r", session_id="s", user_id="u", text="hi", channel="async-task",
                   mode="direct_only", provider="claude", state_home=str(home))
    with patch.object(PROVIDERS["claude"], "run", side_effect=fake_run):
        out = router.route(json.dumps(payload))
    assert out["status"] == "success" and seen["during"] == str(home)
    assert PROVIDERS["claude"].state_home is None


def test_router_without_state_home_grants_nothing():
    seen = {}

    def fake_run(prompt, **_):
        seen["during"] = PROVIDERS["claude"].state_home
        return "ok"

    payload = dict(request_id="r", session_id="s", user_id="u", text="hi", channel="async-task",
                   mode="direct_only", provider="claude")
    with patch.object(PROVIDERS["claude"], "run", side_effect=fake_run):
        router.route(json.dumps(payload))
    assert seen["during"] is None


# --- launch through a real subprocess with a stand-in client ----------------

@pytest.mark.parametrize("name", GRANTED)
def test_subprocess_receives_the_grant_and_prompt(name, home, tmp_path, monkeypatch):
    """The stand-in client records its argv: the grant reaches the process, prompt intact."""
    record = tmp_path / "argv.json"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / name
    fake.write_text(f"#!{os.sys.executable}\nimport json,sys\n"
                    f"open({str(record)!r},'w').write(json.dumps(sys.argv[1:]))\nprint('done')\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    PROVIDERS[name].state_home = str(home)
    assert PROVIDERS[name].run("write the file") == "done"
    got = json.loads(record.read_text())
    assert got.count("--add-dir") >= 1 and str(home) in got
    assert "write the file" in got
    assert got[got.index(str(home)) - 1] == "--add-dir"
