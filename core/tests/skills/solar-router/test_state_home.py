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


def argv(name, prompt="do it", home=None):
    with patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"):
        return PROVIDERS[name].get_cmd(prompt, state_home=str(home) if home else None)


# --- the grant table --------------------------------------------------------

def test_table_has_exactly_the_four_verified_clients():
    assert sorted(STATE_HOME_GRANTS) == sorted(GRANTED)
    assert all(g.flag == "--add-dir" for g in STATE_HOME_GRANTS.values())


@pytest.mark.parametrize("name,expected", [
    ("claude", ["/bin/c", "-p", "P"]),
    ("codex", ["/bin/c", "exec", "--", "P"]),
    ("agent", ["/bin/c", "-p", "P"]),
    ("agy", ["/bin/c", "--sandbox", "--print", "P"]),
])
def test_no_state_home_leaves_the_command_unchanged(name, expected, monkeypatch):
    """With a fixed client command, no declaration adds nothing: exactly the command plus the prompt."""
    monkeypatch.setenv(f"SOLAR_ROUTER_{name.upper()}_CMD", {
        "claude": "c -p", "codex": "c exec --", "agent": "c -p", "agy": "c --sandbox"}[name])
    assert argv(name, "P") == expected
    assert "--add-dir" not in argv(name, "P")


@pytest.mark.parametrize("name", GRANTED)
def test_grant_adds_only_the_state_home(name, home):
    baseline = argv(name)
    granted = argv(name, home=home)
    assert granted.count("--add-dir") == baseline.count("--add-dir") + 1
    # the only new path is the skill folder: no parent, no sibling
    new_paths = [a for a in granted if a.startswith("/") and a not in baseline]
    assert new_paths == [str(home)]


def test_claude_puts_the_prompt_before_the_variadic_option(home):
    cmd = argv("claude", "PROMPT", home)
    assert cmd[-3:] == ["PROMPT", "--add-dir", str(home)]


def test_codex_grant_stays_before_the_separator(home):
    cmd = argv("codex", "PROMPT", home)
    sep = cmd.index("--")
    assert cmd.index("--add-dir") < sep and cmd[sep + 1:] == ["PROMPT"]


def test_agent_and_agy_keep_the_prompt_last(home):
    assert argv("agent", "PROMPT", home)[-3:] == ["--add-dir", str(home), "PROMPT"]
    assert argv("agy", "PROMPT", home)[-4:] == ["--add-dir", str(home), "--print", "PROMPT"]


def test_env_override_still_receives_the_grant(home, monkeypatch):
    monkeypatch.setenv("SOLAR_ROUTER_CODEX_CMD", "mycodex exec --")
    assert argv("codex", "P", home)[1:] == ["exec", "--add-dir", str(home), "--", "P"]


def test_ollama_refuses_a_state_home(home):
    with pytest.raises(StateHomeError) as err:
        PROVIDERS["ollama"].run("hi", state_home=str(home))
    assert err.value.code == "state_home_unsupported_provider"


@pytest.mark.parametrize("bad", ["relative/dir", "/does/not/exist"])
def test_missing_or_relative_home_is_an_error_not_a_fallback(bad):
    with patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"), \
            pytest.raises(StateHomeError) as err:
        PROVIDERS["claude"].get_cmd("x", state_home=bad)
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


def test_a_rejected_home_creates_nothing_at_the_link_target(tmp_path):
    """The location is validated before the folder is created: a planet bucket that is a link to
    another existing folder is refused without making the skill folder at the target."""
    ws = tmp_path / "workspace"
    make_skill(ws)
    root = tmp_path / "app-data" / "Solar" / "planets"
    root.mkdir(parents=True)
    target = tmp_path / "elsewhere" / "p"
    target.mkdir(parents=True)
    (root / "p").symlink_to(target)
    with patch("solar_runtime.planets_root", return_value=root), \
            patch("solar_runtime.planet_bucket", return_value="p"):
        with pytest.raises(StateHomeError) as err:
            resolve_state_home(ws, "p", "watch")
    assert err.value.code == "state_home_unavailable"
    assert list(target.iterdir()) == []


# --- the router scope -------------------------------------------------------

def names(ws, planet="p", skill="watch"):
    return {"planet": planet, "skill": skill, "workspace": str(ws)}


def payload_with(state_home, channel="async-task", **extra):
    return json.dumps(dict(request_id="r", session_id="s", user_id="u", text="hi", channel=channel,
                           mode="direct_only", provider="claude", state_home=state_home, **extra))


def test_router_passes_the_grant_with_the_call(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    expected = resolve_state_home(ws, "p", "watch")
    seen = {}

    def fake_run(prompt, **kw):
        seen["during"] = kw.get("state_home")
        return "ok"

    with patch.object(router, "SOLAR_WORKSPACE", ws), \
            patch.object(PROVIDERS["claude"], "run", side_effect=fake_run):
        out = router.route(payload_with(names(ws)))
    assert out["status"] == "success" and seen["during"] == str(expected)


@pytest.mark.parametrize("value", ["/", os.path.expanduser("~"), "/tmp", {"path": "/"},
                                   {"planet": "p", "skill": "../other", "workspace": "/x"}, {"planet": "p"}])
def test_router_refuses_a_path_or_a_bad_declaration(value, tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    with patch.object(router, "SOLAR_WORKSPACE", ws), \
            patch.object(PROVIDERS["claude"], "run", side_effect=AssertionError("must not run")):
        out = router.route(payload_with(value))
    assert out["status"] == "failed" and out["error_code"] == "state_home_invalid"


def test_router_only_grants_to_async_task_requests(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    with patch.object(router, "SOLAR_WORKSPACE", ws), \
            patch.object(PROVIDERS["claude"], "run", side_effect=AssertionError("must not run")):
        out = router.route(payload_with(names(ws), channel="app"))
    assert out["error_code"] == "state_home_invalid"


def test_router_refuses_a_skill_that_did_not_opt_in(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws, declared=None)
    with patch.object(router, "SOLAR_WORKSPACE", ws):
        out = router.route(payload_with(names(ws)))
    assert out["error_code"] == "state_home_not_declared"


def test_router_refuses_a_restricted_request_before_creating_anything(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    with patch.object(router, "SOLAR_WORKSPACE", ws), \
            patch.object(router, "resolve_state_home", side_effect=AssertionError("must not resolve")):
        out = router.route(payload_with(names(ws), execution={"task_id": "t"}))
    assert out["error_code"] == "state_home_invalid"


def test_router_refuses_a_workspace_that_is_not_its_own(tmp_path):
    ws, other = tmp_path / "workspace", tmp_path / "other"
    make_skill(ws)
    with patch.object(router, "SOLAR_WORKSPACE", ws):
        out = router.route(payload_with(names(other)))
    assert out["error_code"] == "state_home_invalid"


def test_router_reads_the_declaration_the_way_it_dispatches_the_request(tmp_path):
    """A request only the tolerant parser accepts (raw newline in a string) still gets its grant."""
    ws = tmp_path / "workspace"
    make_skill(ws)
    strict = payload_with(names(ws))
    raw = strict.replace('"text": "hi"', '"text": "hi\nthere"'.replace("\\n", "\n"))
    assert "\n" in raw
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    seen = {}

    def fake_run(prompt, **kw):
        seen["kw"] = kw
        return "ok"

    with patch.object(router, "SOLAR_WORKSPACE", ws), patch.object(PROVIDERS["claude"], "run", side_effect=fake_run):
        out = router.route(raw)
    assert out["status"] == "success" and "state_home" in seen["kw"]


def test_router_stream_refuses_with_the_same_code(tmp_path):
    ws = tmp_path / "workspace"
    with patch.object(router, "SOLAR_WORKSPACE", ws):
        events = [json.loads(e) for e in router.route_stream(payload_with("/"))]
    assert events[-1]["status"] == "failed" and events[-1]["error_code"] == "state_home_invalid"


def test_router_without_state_home_grants_nothing():
    seen = {}

    def fake_run(prompt, **kw):
        seen["kw"] = kw
        return "ok"

    payload = dict(request_id="r", session_id="s", user_id="u", text="hi", channel="async-task",
                   mode="direct_only", provider="claude")
    with patch.object(PROVIDERS["claude"], "run", side_effect=fake_run):
        router.route(json.dumps(payload))
    assert "state_home" not in seen["kw"]


def test_interleaved_streams_never_share_a_grant(tmp_path):
    """One stream with a home and one without, suspended in turn: each keeps its own."""
    seen = {"a": [], "b": []}

    def fake_stream(tag):
        def stream(prompt, **kw):
            for i in range(3):
                seen[tag].append(kw.get("state_home"))
                yield f"{tag}{i}"
        return stream

    a = router.stream_provider("x", "claude", "/granted/home")
    b = router.stream_provider("y", "claude", None)
    with patch.object(PROVIDERS["claude"], "stream", side_effect=lambda p, **kw: fake_stream("a" if p == "x" else "b")(p, **kw)):
        order = [next(a), next(b), next(a), next(b), next(a), next(b)]
    assert [c for c, _ in order] == ["a0", "b0", "a1", "b1", "a2", "b2"]
    assert seen["a"] == ["/granted/home"] * 3 and seen["b"] == [None] * 3


def test_pinned_ollama_keeps_the_state_home_error_code(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    payload = json.dumps(dict(request_id="r", session_id="s", user_id="u", text="hi", channel="async-task",
                              mode="direct_only", provider="ollama", state_home=names(ws)))
    with patch.object(router, "SOLAR_WORKSPACE", ws):
        out = router.route(payload)
    assert out["status"] == "failed" and out["error_code"] == "state_home_unsupported_provider"


def test_home_that_vanishes_before_launch_keeps_its_code(tmp_path):
    ws = tmp_path / "workspace"
    make_skill(ws)
    gone = str(tmp_path / "gone")
    with patch.object(router, "_state_home_request", return_value=(gone, None)), \
            patch("providers.base.shutil.which", side_effect=lambda b, path=None: f"/bin/{b}"):
        out = router.route(payload_with(names(ws)))
    assert out["status"] == "failed" and out["error_code"] == "state_home_unavailable"


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
    assert PROVIDERS[name].run("write the file", state_home=str(home)) == "done"
    got = json.loads(record.read_text())
    assert got.count("--add-dir") >= 1 and str(home) in got
    assert "write the file" in got
    assert got[got.index(str(home)) - 1] == "--add-dir"
