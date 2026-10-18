"""No-inference Cursor/Agy contracts and refusal paths."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import execution_profiles as profiles
import repository_cli_guards as guards
import repository_reviews as repo
from providers import PROVIDERS
from git_review_fixture import repository


def auth_fixture(home):
    cursor = home / ('.cursor' if sys.platform == 'darwin' else '.config/cursor')
    guards.write_json(cursor / 'auth.json', dict(accessToken='fixture-access', refreshToken='fixture-refresh', apiKey='DO-NOT-COPY'))
    token = home / '.gemini/jetski-standalone-oauth-token'
    token.parent.mkdir(parents=True, exist_ok=True); token.write_text('fixture-token')
    guards.write_json(home / '.gemini/antigravity-cli/settings.json', dict(toolPermission='always-proceed'))


@pytest.mark.parametrize('provider', ['agent', 'agy'])
@pytest.mark.parametrize('stream', [False, True])
def test_new_providers_use_native_router_bound_review_and_isolated_configuration(tmp_path, monkeypatch, provider, stream):
    import router
    import solar_state
    source, commit = repository(tmp_path)
    e = repo.build(repository=str(source), commit=commit, provider=provider, model='fixture-model',
                   instructions='Review the committed version.', rules=[])
    home = tmp_path / 'user'; auth_fixture(home)
    monkeypatch.setenv('HOME', str(home))
    for key in ['CURSOR_API_KEY', 'GEMINI_API_KEY', 'ANTIGRAVITY_PERM_GRANTS', 'NODE_OPTIONS']:
        monkeypatch.setenv(key, 'HOSTILE')
    for key in list(os.environ):
        if key.startswith(('SOLAR_ROUTER_' + provider.upper() + '_', 'SOLAR_AI_' + provider.upper() + '_')):
            monkeypatch.delenv(key)
    # OS enforcement is exercised separately; doubles must run on sandboxes and
    # Linux hosts without bubblewrap too. Here only that boundary is replaced.
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    record = tmp_path / 'called.json'
    binary = tmp_path / provider
    binary.write_text(f'''#!{sys.executable}
import json,os,pathlib,sys
if '--version' in sys.argv: print('2026.10.14-0f9edde')
elif '--help' in sys.argv: print('--mode read-only plan --sandbox --model --output-format --workspace --trust --disable-slash-commands')
else:
 home=pathlib.Path(os.environ['HOME'])
 config=home/('.cursor/cli-config.json' if {provider!r}=='agent' else '.gemini/antigravity-cli/settings.json')
 pathlib.Path({str(record)!r}).write_text(json.dumps(dict(argv=sys.argv[1:],env=dict(os.environ),
  config=json.loads(config.read_text()),cwd=os.getcwd(),source=pathlib.Path('operations.md').read_text())))
 if {provider!r}=='agy': print(json.dumps(dict(status='SUCCESS',response='Bound review',usage=dict(input_tokens=4,output_tokens=2))))
 else: print(json.dumps(dict(type='result',subtype='success',result='Bound review',usage=dict(inputTokens=4,outputTokens=2,cacheReadTokens=0))))
''')
    binary.chmod(0o700)
    monkeypatch.setattr(PROVIDERS[provider], 'resolve_binary', lambda _: str(binary))
    for loader in ['read_system_prompt', 'conversation_context', 'load_continuity', 'resolve_jit_context']:
        monkeypatch.setattr(router, loader, lambda *a, **k: pytest.fail('ambient context loaded'))
    fields = dict(provider=provider, execution_profile=repo.PROFILE,
                  access_policy=profiles.canonical(dict(version=1, mode='read', scopes=[str(source)], resources=[])),
                  review_input_manifest=profiles.canonical(e['manifest']), review_input_digest=e['review_input_digest'])
    with solar_state.session() as store:
        task = store.task_create([(k, json.dumps(v)) for k, v in fields.items()], 'Review.', status='queued')
        claim = store.task_claim_detail(task, 'reader')
    assert claim['claimed']
    payload = dict(text='UNAPPROVED', provider=provider,
                   execution=dict(task_id=task, token=claim['token'], profile=repo.PROFILE))
    result = ([json.loads(line) for line in router.route_stream(json.dumps(payload))][-1]
              if stream else router.route(json.dumps(payload)))
    assert result['status'] == 'success', result
    assert commit in result['reply_text']
    called = json.loads(record.read_text())
    assert called['source'] == 'The maximum batch is five.\n'
    assert 'HOSTILE' not in called['env'].values()
    assert 'UNAPPROVED' not in ''.join(called['argv'])
    assert not Path(called['cwd']).exists() and not Path(called['env']['HOME']).exists()
    assert '--force' not in called['argv'] and '--dangerously-skip-permissions' not in called['argv']
    if provider == 'agent':
        assert called['config']['permissions']['deny'] == ['Write(**)', 'Shell(*)', 'Mcp(*:*)', 'WebFetch(*)']
        assert called['env']['AGENT_CLI_CREDENTIAL_STORE'] == 'file'
        assert '--trust' in called['argv'] and '--approve-mcps' not in called['argv']
        assert called['argv'][called['argv'].index('--mode') + 1] == 'ask'
    else:
        assert called['config']['toolPermission'] == 'strict'
        assert 'write_file(*)' in called['config']['permissions']['deny']
        assert 'mcp(*)' in called['config']['permissions']['deny']
        assert '--disable-slash-commands' in called['argv']
    record.unlink()
    payload['execution']['token'] = 'stale'
    assert router.route(json.dumps(payload))['error_code'] == 'review_input_mismatch'
    assert not record.exists()


@pytest.mark.parametrize('provider', ['agent', 'agy'])
def test_unavailable_guard_refuses_before_cli_or_inference(tmp_path, monkeypatch, provider):
    home = tmp_path / 'user'; auth_fixture(home)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('unchanged')
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: (_ for _ in ()).throw(guards.refused()))
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        guards.prepare(provider, '/no-provider-should-run', {'HOME': str(home)}, private, cwd,
                       dict(system_prompt='Review.', user_prompt='Version.', model='fixed'))


@pytest.mark.parametrize('provider', ['agent', 'agy'])
def test_unknown_help_refuses_and_launch_context_cleans_up(tmp_path, monkeypatch, provider):
    source, commit = repository(tmp_path)
    e = repo.build(repository=str(source), commit=commit, provider=provider, model='fixed', instructions='Review.', rules=[])
    home = tmp_path / 'user'; auth_fixture(home); monkeypatch.setenv('HOME', str(home))
    binary = tmp_path / provider; binary.write_text('#!/bin/sh\necho unknown\n'); binary.chmod(0o700)
    monkeypatch.setattr(PROVIDERS[provider], 'resolve_binary', lambda _: str(binary))
    seen = []
    monkeypatch.setattr(guards, 'guard_prefix', lambda private, cwd: seen.append(private) or [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    with pytest.raises(profiles.ProfileError):
        with repo.launch(PROVIDERS[provider], e['manifest'], e['review_input_digest'], lambda: None):
            pytest.fail('unknown help accepted')
    assert seen and not seen[0].exists()


def test_missing_or_linked_credentials_are_refused(tmp_path):
    source = tmp_path / 'auth'; source.write_text('token'); link = tmp_path / 'link'; link.symlink_to(source)
    for path in (link, tmp_path / 'missing'):
        with pytest.raises(profiles.ProfileError): guards.credential(path, tmp_path / 'copy')
    assert not (tmp_path / 'copy').exists()


def test_cursor_copies_subscription_tokens_only(tmp_path):
    home = tmp_path / 'user'; auth_fixture(home)
    isolated = tmp_path / 'isolated'
    guards.cursor_auth(home, isolated)
    path = isolated / ('.cursor' if sys.platform == 'darwin' else '.config/cursor') / 'auth.json'
    assert json.loads(path.read_text()) == dict(accessToken='fixture-access', refreshToken='fixture-refresh')
    assert path.stat().st_mode & 0o777 == 0o600


def test_guard_configuration_is_fail_closed_without_linux_helper(tmp_path, monkeypatch):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    monkeypatch.setattr(guards.sys, 'platform', 'linux')
    monkeypatch.setattr(guards.shutil, 'which', lambda *a, **k: None)
    with pytest.raises(profiles.ProfileError): guards.guard_prefix(private, cwd)


@pytest.mark.skipif(os.getenv('SOLAR_TEST_REPOSITORY_CLI') != '1', reason='opt-in real OS guard; no inference')
def test_real_os_guard_blocks_overwrite_creation_and_host_writes(tmp_path, monkeypatch):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'source.md').write_text('unchanged')
    origin = tmp_path / 'real-user'
    guards.write_json(origin / '.cursor/cli-config.json', dict(untrusted=True))
    monkeypatch.setenv('HOME', str(origin))
    prefix = guards.guard_prefix(private, cwd)
    guards.probe_guard(prefix, dict(os.environ), private, cwd)
    code = '''import pathlib,sys
try: pathlib.Path(sys.argv[1]).read_text()
except OSError: sys.exit(0)
sys.exit(13)
'''
    done = subprocess.run([*prefix, sys.executable, '-B', '-c', code,
                           str(origin / '.cursor/cli-config.json')], capture_output=True, timeout=15)
    assert done.returncode == 0
    assert (cwd / 'source.md').read_text() == 'unchanged'
    assert not (cwd / '.solar-write-probe').exists()


@pytest.mark.parametrize('provider,output', [
    ('agy', dict(status='FAILED', response='Do not accept')),
    ('agy', dict(status='SUCCESS', response='Do not accept', error='refused')),
    ('agy', dict(response='Unknown status')),
    ('agy', dict(status='SUCCESS')),
    ('agent', dict(type='result', subtype='error', result='Do not accept')),
    ('agent', dict(type='result', subtype='success', is_error=True, result='Do not accept')),
    ('agent', []),
])
def test_native_error_envelopes_never_become_successful_reviews(tmp_path, monkeypatch, provider, output):
    from contextlib import contextmanager
    @contextmanager
    def launch(*a, **k):
        yield [sys.executable, '-c', 'print(' + repr(json.dumps(output)) + ')'], dict(os.environ), str(tmp_path)
    monkeypatch.setattr(profiles, 'restricted_launch', launch)
    with pytest.raises(RuntimeError, match='restricted provider returned'):
        PROVIDERS[provider].run_review(manifest={}, expected='unused', profile=repo.PROFILE)


def test_linux_guard_keeps_host_and_snapshot_read_only(tmp_path, monkeypatch):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    monkeypatch.setattr(guards.sys, 'platform', 'linux')
    monkeypatch.setattr(guards.shutil, 'which', lambda *a, **k: '/usr/bin/bwrap')
    argv = guards.guard_prefix(private, cwd)
    assert argv[:2] == ['/usr/bin/bwrap', '--die-with-parent']
    assert argv[argv.index('--bind') + 1:argv.index('--bind') + 3] == [str(private), str(private)]
    assert argv.count('--ro-bind') == 2
    assert argv[-1] == '--'


def test_probe_refuses_a_guard_that_allows_snapshot_writes(tmp_path):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'source.md').write_text('unchanged')
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        guards.probe_guard([], dict(os.environ), private, cwd)


def test_cursor_unknown_version_refuses_private_file_store(tmp_path, monkeypatch):
    source, commit = repository(tmp_path)
    e = repo.build(repository=str(source), commit=commit, provider='agent', model='fixed', instructions='Review.', rules=[])
    home = tmp_path / 'user'; auth_fixture(home); monkeypatch.setenv('HOME', str(home))
    binary = tmp_path / 'agent'
    binary.write_text('#!/bin/sh\necho "--mode read-only --sandbox --model --output-format --workspace --trust unknown-version"\n')
    binary.chmod(0o700)
    monkeypatch.setattr(PROVIDERS['agent'], 'resolve_binary', lambda _: str(binary))
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    with pytest.raises(profiles.ProfileError):
        with repo.launch(PROVIDERS['agent'], e['manifest'], e['review_input_digest'], lambda: None):
            pytest.fail('unknown file-store behavior accepted')
