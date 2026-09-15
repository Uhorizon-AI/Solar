"""User-level MCP registration: merge JSON/TOML without clobbering other servers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib

import pytest

from pathlib import Path

import mcp_cli


@pytest.fixture(autouse=True)
def isolated_registration(tmp_path, monkeypatch):
    monkeypatch.setenv('SOLAR_APP_DATA', str(tmp_path / 'app-data'))
    monkeypatch.setenv('SOLAR_MCP_PYTHON', sys._base_executable)



def test_upsert_toml_keeps_chrome():
    src = (
        "[mcp_servers.chrome-devtools]\n"
        'command = "npx"\n'
        "enabled = true\n"
        "\n"
        "[features]\n"
        "foo = true\n"
    )
    out = mcp_cli.upsert_toml_table(
        src, "mcp_servers.solar", mcp_cli.toml_block(Path("/ws"))
    )
    assert "[mcp_servers.chrome-devtools]" in out
    assert "[features]" in out
    assert "[mcp_servers.solar]" in out
    assert 'args = ["mcp"]' in out
    assert "SOLAR_WORKSPACE" in out


def test_upsert_toml_replaces_existing_solar():
    src = (
        "[mcp_servers.solar]\n"
        'command = "/old/solar"\n'
        "\n"
        "[mcp_servers.solar.env]\n"
        'SOLAR_WORKSPACE = "/old"\n'
        "\n"
        "[mcp_servers.chrome-devtools]\n"
        'command = "npx"\n'
    )
    out = mcp_cli.upsert_toml_table(
        src, "mcp_servers.solar", mcp_cli.toml_block(Path("/new-ws"))
    )
    assert out.count("[mcp_servers.solar]") == 1
    assert "/old/solar" not in out
    assert "/new-ws" in out
    assert "[mcp_servers.chrome-devtools]" in out


def test_merge_json_keeps_chrome(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"chrome-devtools": {"command": "npx"}}}) + "\n",
        encoding="utf-8",
    )
    mcp_cli.merge_json_servers(
        path,
        {"command": "/bin/solar", "args": ["mcp"], "env": {"SOLAR_WORKSPACE": "/ws"}},
        create=False,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["chrome-devtools"]["command"] == "npx"
    assert data["mcpServers"]["solar"]["args"] == ["mcp"]


def test_print_snippets(capsys, monkeypatch, tmp_path):
    wrapper = tmp_path / "solar"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.setattr(mcp_cli, "solar_bin", lambda: str(wrapper))
    mcp_cli.print_snippets(Path("/Users/me/Solar"))
    out = capsys.readouterr().out
    assert str(wrapper) in out
    assert 'args = ["mcp"]' in out
    blocks = out.split('=== ')
    for name in ('cursor', 'claude'):
        block = next(part for part in blocks if part.startswith(name + ':'))
        data, _ = json.JSONDecoder().raw_decode(block.split(' ===\n', 1)[1].lstrip())
        assert data['mcpServers']['solar']['args'] == ['mcp']
    assert "SOLAR_MCP_PYTHON" in out
    assert "/Users/me/Solar" in out



@pytest.mark.parametrize('header', ['[mcp_servers.solar] # note', '[mcp_servers."solar"]', "[mcp_servers.'solar']"])
def test_toml_headers_preserve_other_sections(header):
    source = header + '\ncommand="old"\n[features] # note\nfoo=true\n[[plugins]]\nname="keep"\n'
    result = mcp_cli.upsert_toml_table(source, 'mcp_servers.solar', mcp_cli.toml_block(Path('/ws')))
    data = tomllib.loads(result)
    assert data['features'] == {'foo': True}
    assert data['plugins'] == [{'name': 'keep'}]
    assert data['mcp_servers']['solar']['args'] == ['mcp']


def test_toml_multiline_string_preserved():
    source = 'description = """\n[mcp_servers.solar]\nnot a table\n"""\n'
    result = mcp_cli.upsert_toml_table(source, 'mcp_servers.solar', mcp_cli.toml_block(Path('/ws')))
    assert tomllib.loads(result)['description'] == tomllib.loads(source)['description']


def test_inline_toml_fails_without_writing(tmp_path):
    path = tmp_path / 'config.toml'
    source = '[mcp_servers]\nsolar = {command="old"}\n'
    path.write_text(source)
    with pytest.raises(ValueError):
        mcp_cli.merge_codex_toml(path, Path('/ws'), create=False)
    assert path.read_text() == source
    assert not list(tmp_path.glob('*.bak*'))


def test_install_idempotent_and_uninstall_preserves_others(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.setattr(mcp_cli, 'solar_bin', lambda: '/bin/solar')
    path = tmp_path / '.cursor/mcp.json'
    path.parent.mkdir()
    path.write_text('{"mcpServers":{"other":{"command":"keep"}}}')
    assert mcp_cli.install(Path('/ws'), ['cursor', 'claude', 'codex']) == 0
    assert not (tmp_path / '.claude.json').exists()
    backup = path.with_name(path.name + '.bak.solar-mcp')
    before = (path.stat().st_mtime_ns, backup.read_bytes(), backup.stat().st_mtime_ns)
    assert mcp_cli.install(Path('/ws'), ['cursor', 'codex']) == 0
    assert before == (path.stat().st_mtime_ns, backup.read_bytes(), backup.stat().st_mtime_ns)
    assert mcp_cli.install(None, ['cursor', 'codex'], uninstall=True) == 0
    assert json.loads(path.read_text())['mcpServers'] == {'other': {'command': 'keep'}}
    assert 'solar' not in tomllib.loads((tmp_path / '.codex/config.toml').read_text()).get('mcp_servers', {})


def test_dry_run_no_files_and_diff(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('CODEX_HOME', raising=False)
    assert mcp_cli.install(Path('/ws'), ['cursor', 'codex'], dry_run=True) == 0
    assert not (tmp_path / '.cursor').exists()
    assert not (tmp_path / '.codex').exists()
    assert 'solar (after)' in capsys.readouterr().out


def test_invalid_json_reports_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HOME', str(tmp_path))
    path = tmp_path / '.cursor/mcp.json'
    path.parent.mkdir()
    path.write_text('{broken')
    assert mcp_cli.install(Path('/ws'), ['cursor']) == 1
    assert 'ERROR' in capsys.readouterr().err
    assert path.read_text() == '{broken'


def test_concurrent_change_is_not_overwritten(tmp_path):
    path = tmp_path / 'config.json'
    path.write_bytes(b'new writer')
    with pytest.raises(ValueError, match='Concurrent'):
        mcp_cli.write_config(path, b'old writer', b'ours', False)
    assert path.read_bytes() == b'new writer'


def test_atomic_replace_failure_keeps_config(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    path.write_bytes(b'old')
    real_replace = os.replace
    def fail(source, destination):
        if destination == path:
            raise OSError('simulated crash')
        real_replace(source, destination)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        mcp_cli.write_config(path, b'old', b'new', False)
    assert path.read_bytes() == b'old'


def test_workspace_resolves_parent(solar_env, monkeypatch):
    planet = solar_env.workspace / 'planets/test'
    planet.mkdir(parents=True)
    monkeypatch.chdir(planet)
    assert mcp_cli.workspace_path(None) == solar_env.workspace
    assert mcp_cli.main(['install', '--workspace', '/does-not-exist', '--dry-run']) == 2


def test_bundle_contains_mcp():
    import client_bundle_build as bundle
    core = Path(mcp_cli.__file__).resolve().parents[3]
    selected, _ = bundle.expand_allowlist(bundle.discover_skills(core, Path('/nonexistent')), core)
    assert {'solar-mcp', 'solar-telegram', 'solar-client', 'solar-app', 'solar-router', 'solar-async-tasks'} <= selected.keys()


def test_dispatcher_handshake(solar_env):
    dispatcher = Path(mcp_cli.__file__).resolve().parents[2] / 'solar-client/scripts/solar'
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}}
    env = dict(solar_env.env, SOLAR_MCP_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run(['bash', str(dispatcher), 'mcp'], input=json.dumps(request)+'\n',
                            capture_output=True, text=True, env=env, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['result']['serverInfo']['name'] == 'solar-mcp'


def test_interpreter_preserves_stable_symlink(tmp_path, monkeypatch):
    stable = tmp_path / 'python3'
    stable.symlink_to(sys._base_executable)
    monkeypatch.setenv('SOLAR_MCP_PYTHON', str(stable))
    assert mcp_cli.registration_python() == str(stable)


def test_venv_interpreter_rejected(monkeypatch):
    monkeypatch.setenv('SOLAR_MCP_PYTHON', sys.executable)
    if sys.prefix == sys.base_prefix:
        pytest.skip('test runner must use a venv')
    with pytest.raises(ValueError, match='non-venv'):
        mcp_cli.registration_python()


def test_stable_selection_from_venv(monkeypatch):
    monkeypatch.setenv('SOLAR_MCP_PYTHON', sys._base_executable)
    assert mcp_cli.registration_python() == sys._base_executable


def test_stdio_does_not_import_tomllib(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def no_toml(name, *args, **kwargs):
        if name == 'tomllib':
            raise ImportError('simulated Python 3.10')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_toml)
    monkeypatch.setattr(os, 'execv', lambda *args: (_ for _ in ()).throw(SystemExit(0)))
    with pytest.raises(SystemExit) as exc:
        mcp_cli.main([])
    assert exc.value.code == 0
    assert mcp_cli.main(['print']) == 2


def test_path_interpreter_selection(tmp_path, monkeypatch):
    stable = tmp_path / 'python3'
    stable.symlink_to(sys._base_executable)
    monkeypatch.delenv('SOLAR_MCP_PYTHON')
    monkeypatch.setenv('PATH', str(tmp_path))
    assert mcp_cli.registration_python() == str(stable)


def test_locks_stay_in_runtime(tmp_path):
    path = tmp_path / '.claude.json'
    path.write_text('{}')
    mcp_cli.merge_json_servers(path, {'command': 'solar'}, create=False)
    assert not list(tmp_path.glob('*.lock'))
    locks = list((tmp_path / 'app-data').rglob('*.lock'))
    assert len(locks) == 1
    first_inode = locks[0].stat().st_ino
    mcp_cli.merge_json_servers(path, {'command': 'changed'}, create=False)
    assert locks[0].stat().st_ino == first_inode


def test_registration_resolved_once(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(mcp_cli, 'registration_python', lambda: calls.append('python') or '/stable/python3')
    monkeypatch.setattr(mcp_cli, 'solar_bin', lambda: calls.append('solar') or '/stable/solar')
    monkeypatch.setenv('HOME', str(tmp_path))
    mcp_cli.print_snippets(Path('/ws'))
    assert calls == ['python', 'solar']
    calls.clear()
    mcp_cli.install(Path('/ws'), ['cursor', 'claude', 'codex'], dry_run=True)
    assert calls == ['python', 'solar']


def test_invalid_interpreter_has_no_partial_output(monkeypatch, capsys):
    def fail():
        raise ValueError('invalid interpreter')
    monkeypatch.setattr(mcp_cli, 'registration_python', fail)
    with pytest.raises(ValueError):
        mcp_cli.print_snippets(Path('/ws'))
    assert capsys.readouterr().out == ''
