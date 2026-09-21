"""The installation secrets have one home, and it is not the workspace.

Every test here redirects `SOLAR_SECRETS_FILE` (or `SOLAR_APP_DATA`) into a
temporary directory. Nothing reads or writes the machine's real store: the point
of the change is that these keys stop living where things can stumble onto them,
and a test suite is a thing that can stumble onto them.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[3]
_SCRIPTS = _CORE / "skills" / "solar-paths" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import solar_secrets  # noqa: E402


@pytest.fixture(autouse=True)
def fixture_store(tmp_path, monkeypatch):
    """A store in a temp dir, for this test only."""
    store = tmp_path / "app-data" / "Solar" / "secrets" / "installation.env"
    monkeypatch.setenv("SOLAR_APP_DATA", str(tmp_path / "app-data"))
    monkeypatch.setenv("SOLAR_SECRETS_FILE", str(store))
    return store


def test_the_store_is_outside_the_workspace_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SOLAR_SECRETS_FILE", raising=False)
    monkeypatch.setenv("SOLAR_APP_DATA", str(tmp_path / "app-data"))
    path = solar_secrets.secrets_file()
    assert path.name == "installation.env"
    assert "Solar/secrets" in str(path)
    # Not in a workspace, not in a repo, not in anything an IDE opens.
    assert "/sun/" not in str(path) and not str(path).endswith(".env.local")


def test_ensure_creates_an_empty_hole_the_owner_alone_can_read(fixture_store):
    path = solar_secrets.ensure_store()
    assert path == fixture_store and path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # A hole, not a value: the installer creates it, Louis fills it.
    assert solar_secrets.read() == {}


def test_ensure_never_overwrites_a_value(fixture_store):
    solar_secrets.ensure_store()
    fixture_store.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    solar_secrets.ensure_store()
    assert solar_secrets.read()["TELEGRAM_BOT_TOKEN"] == "123:abc"


def test_it_parses_what_a_shell_would(fixture_store):
    solar_secrets.ensure_store()
    fixture_store.write_text(
        "# a comment\n"
        "\n"
        "TELEGRAM_BOT_TOKEN=123:abc\n"
        'export SOLAR_N8N_WEBHOOK_SECRET="s3cr3t"\n'
        "not a pair\n",
        encoding="utf-8")
    assert solar_secrets.read() == {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "SOLAR_N8N_WEBHOOK_SECRET": "s3cr3t",
    }


def test_the_store_wins_over_a_stale_copy_in_the_environment(fixture_store):
    solar_secrets.ensure_store()
    fixture_store.write_text("TELEGRAM_BOT_TOKEN=fresh\n", encoding="utf-8")
    environ = {"TELEGRAM_BOT_TOKEN": "stale-from-dot-env"}
    loaded = solar_secrets.load_into_environ(environ)
    assert loaded == ["TELEGRAM_BOT_TOKEN"]
    assert environ["TELEGRAM_BOT_TOKEN"] == "fresh"


def test_it_reports_a_key_left_behind_in_the_workspace(tmp_path):
    """The closing condition of the change, as something a script can check."""
    workspace = tmp_path / "workspace"
    (workspace / "sun").mkdir(parents=True)
    (workspace / ".env").write_text(
        "TELEGRAM_CHAT_ID=999\nTELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    (workspace / "sun" / ".env").write_text("OPENAI_API_KEY=x\n", encoding="utf-8")

    leaks = solar_secrets.workspace_leaks(workspace)
    assert leaks == [f"{workspace / '.env'}:TELEGRAM_BOT_TOKEN"]

    # The chat id is visible configuration and is allowed to stay.
    (workspace / ".env").write_text("TELEGRAM_CHAT_ID=999\n", encoding="utf-8")
    assert solar_secrets.workspace_leaks(workspace) == []


def test_a_commented_out_key_is_not_a_leak(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text(
        "# TELEGRAM_BOT_TOKEN lives in the process store\n", encoding="utf-8")
    assert solar_secrets.workspace_leaks(workspace) == []


def test_there_is_no_verb_that_prints_a_secret(fixture_store):
    """This is not a vault UX: no `get`, and `names` never shows a value."""
    solar_secrets.ensure_store()
    fixture_store.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    env = {**os.environ, "SOLAR_SECRETS_FILE": str(fixture_store)}
    script = str(_SCRIPTS / "solar_secrets.py")

    listed = subprocess.run([sys.executable, script, "names"],
                            capture_output=True, text=True, env=env)
    assert listed.returncode == 0
    assert listed.stdout.strip() == "TELEGRAM_BOT_TOKEN"
    assert "123:abc" not in listed.stdout

    reported = subprocess.run([sys.executable, script, "status"],
                              capture_output=True, text=True, env=env)
    assert "123:abc" not in reported.stdout

    for verb in ("get", "print", "dump"):
        refused = subprocess.run([sys.executable, script, verb],
                                 capture_output=True, text=True, env=env)
        assert refused.returncode == 2, verb


def test_only_the_installation_names_reach_the_environment(fixture_store):
    """A stray key in the store is reported, not loaded.

    The store is the one file Solar's runtime opens with its own hands. What it
    puts in the environment of the gateway, the notifier and the MCP server is
    the allowlist and nothing else, so a name nobody put there on purpose cannot
    ride along into a subprocess.
    """
    solar_secrets.ensure_store()
    fixture_store.write_text(
        "TELEGRAM_BOT_TOKEN=123:abc\n"
        "NOT_A_SECRET=x\n"
        "PATH=/tmp/evil/bin\n",
        encoding="utf-8")

    environ = {}
    loaded = solar_secrets.load_into_environ(environ)
    assert loaded == ["TELEGRAM_BOT_TOKEN"]
    assert environ == {"TELEGRAM_BOT_TOKEN": "123:abc"}

    # Reported, so a doctor can see it; still never loaded.
    assert solar_secrets.status()["unknown"] == ["NOT_A_SECRET", "PATH"]


def test_nothing_in_the_store_is_executed(fixture_store, tmp_path):
    """The file is parsed, never sourced.

    Sourcing would hand the contents to a shell, so a value with `$(...)` or
    backticks would run as a command in the one process holding Solar's
    credentials. The proof is a value that would leave a trace if it ran.
    """
    trace = tmp_path / "executed"
    solar_secrets.ensure_store()
    fixture_store.write_text(
        f"TELEGRAM_BOT_TOKEN=$(touch {trace})\n"
        f"EVIL=$(touch {trace})\n"
        f"BACKTICKS=`touch {trace}`\n",
        encoding="utf-8")

    environ = {}
    solar_secrets.load_into_environ(environ)
    assert not trace.exists(), "the store was evaluated instead of parsed"
    # The allowlisted name arrives verbatim; the others do not arrive at all.
    assert environ == {"TELEGRAM_BOT_TOKEN": f"$(touch {trace})"}


def test_the_bash_loader_executes_nothing_either(fixture_store, tmp_path):
    """Same guarantee on the bash side, which is the one the gateway uses."""
    trace = tmp_path / "executed-by-bash"
    solar_secrets.ensure_store()
    fixture_store.write_text(
        f"TELEGRAM_BOT_TOKEN=$(touch {trace})\n"
        f"EVIL=$(touch {trace})\n"
        "NOT_A_SECRET=x\n",
        encoding="utf-8")
    loader = _SCRIPTS / "solar_secrets.sh"
    proc = subprocess.run(
        ["bash", "-c",
         f'set -euo pipefail; source "{loader}"; solar_load_installation_secrets; '
         'printf "token=%s|evil=%s|other=%s" "${TELEGRAM_BOT_TOKEN:-}" '
         '"${EVIL:-<unset>}" "${NOT_A_SECRET:-<unset>}"'],
        capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k != "TELEGRAM_BOT_TOKEN"}
            | {"SOLAR_SECRETS_FILE": str(fixture_store)})
    assert proc.returncode == 0, proc.stderr
    assert not trace.exists(), "the loader sourced the store instead of parsing it"
    assert proc.stdout == f"token=$(touch {trace})|evil=<unset>|other=<unset>"


def test_the_bash_loader_does_not_abort_a_caller_running_with_set_e(fixture_store):
    """It is sourced into `transport_gateway_lib.sh`, which runs `set -euo pipefail`."""
    solar_secrets.ensure_store()
    fixture_store.write_text(
        "# a comment, then a blank line\n\nTELEGRAM_BOT_TOKEN=123:abc\n"
        "malformed line with no equals sign\n",
        encoding="utf-8")
    loader = _SCRIPTS / "solar_secrets.sh"
    proc = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{loader}"; '
                       'solar_load_installation_secrets; echo "still here"'],
        capture_output=True, text=True,
        env={**os.environ, "SOLAR_SECRETS_FILE": str(fixture_store)})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "still here"


def test_the_bash_loader_reads_the_same_file(fixture_store):
    """The gateway and the notifier are bash; they must see what python sees."""
    solar_secrets.ensure_store()
    fixture_store.write_text("TELEGRAM_BOT_TOKEN=from-the-store\n", encoding="utf-8")
    loader = _SCRIPTS / "solar_secrets.sh"
    proc = subprocess.run(
        ["bash", "-c",
         f'source "{loader}"; solar_load_installation_secrets; '
         'printf "%s" "$TELEGRAM_BOT_TOKEN"'],
        capture_output=True, text=True,
        env={**os.environ, "SOLAR_SECRETS_FILE": str(fixture_store),
             "TELEGRAM_BOT_TOKEN": "stale-from-dot-env"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "from-the-store"


def test_the_bash_loader_survives_a_machine_with_no_store(tmp_path):
    """A machine without transports configured is a valid machine."""
    loader = _SCRIPTS / "solar_secrets.sh"
    proc = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{loader}"; '
                       'solar_load_installation_secrets; echo survived'],
        capture_output=True, text=True,
        env={**os.environ, "SOLAR_SECRETS_FILE": str(tmp_path / "nothing.env")})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "survived"
