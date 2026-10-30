"""No-inference Cursor/Agy contracts and refusal paths."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest
import execution_profiles as profiles
import repository_cli_guards as guards
import repository_reviews as repo
from providers import PROVIDERS
from git_review_fixture import repository


HELP = """Options:
  --print                       Print the response
  --mode <mode>                 Modes: ask (read-only), plan
  --sandbox <mode>              Values: enabled, disabled
  --model <model>               Select a model
  --output-format <format>      Formats: json, text
  --workspace <path>            Select the workspace
  --trust                       Trust the workspace
  --disable-slash-commands      Disable command expansion
  --log-file <path>             Override CLI log file path
"""


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
if '--version' in sys.argv: print('2027.01.01-new-release')
elif '--help' in sys.argv: print({HELP!r})
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
    assert result['review_preflight']['version'] == '2027.01.01-new-release'
    with solar_state.session() as store:
        row = [r for r in store.audit_rows(event='end') if r.get('task_id') == task][-1]
    assert row['review_preflight']['version'] == '2027.01.01-new-release'
    assert '--print' in result['review_preflight']['capabilities_checked']
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
        assert called['argv'][called['argv'].index('--sandbox') + 1] == 'enabled'
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
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: (_ for _ in ()).throw(guards.refused('boundary_unavailable', 'boundary', 'agent')))
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
    monkeypatch.setattr(guards, 'guard_prefix', lambda private, cwd, *a: seen.append(private) or [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    with pytest.raises(profiles.ProfileError):
        with repo.launch(PROVIDERS[provider], e['manifest'], e['review_input_digest'], lambda: None):
            pytest.fail('unknown help accepted')
    assert seen and not seen[0].exists()


def test_missing_or_linked_credentials_are_refused(tmp_path):
    source = tmp_path / 'auth'; source.write_text('token'); link = tmp_path / 'link'; link.symlink_to(source)
    for path in (link, tmp_path / 'missing'):
        with pytest.raises(profiles.ProfileError): guards.credential(path, tmp_path / 'copy', 'agy')
    assert not (tmp_path / 'copy').exists()


def test_cursor_copies_subscription_tokens_only(tmp_path):
    home = tmp_path / 'user'; auth_fixture(home)
    isolated = tmp_path / 'isolated'
    guards.cursor_auth(home, isolated, 'agent')
    path = isolated / ('.cursor' if sys.platform == 'darwin' else '.config/cursor') / 'auth.json'
    assert json.loads(path.read_text()) == dict(accessToken='fixture-access', refreshToken='fixture-refresh')
    assert path.stat().st_mode & 0o777 == 0o600


def test_guard_configuration_is_fail_closed_without_linux_helper(tmp_path, monkeypatch):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    monkeypatch.setattr(guards.sys, 'platform', 'linux')
    monkeypatch.setattr(guards.shutil, 'which', lambda *a, **k: None)
    with pytest.raises(profiles.ProfileError): guards.guard_prefix(private, cwd, 'agent')


@pytest.mark.skipif(os.getenv('SOLAR_TEST_REPOSITORY_CLI') != '1', reason='opt-in real OS guard; no inference')
def test_real_os_guard_blocks_overwrite_creation_and_host_writes(tmp_path, monkeypatch):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'source.md').write_text('unchanged')
    origin = tmp_path / 'real-user'
    guards.write_json(origin / '.cursor/cli-config.json', dict(untrusted=True))
    monkeypatch.setenv('HOME', str(origin))
    prefix = guards.guard_prefix(private, cwd, 'agent')
    guards.probe_guard(prefix, dict(os.environ), private, cwd, 'agent')
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
    argv = guards.guard_prefix(private, cwd, 'agent')
    assert argv[:2] == ['/usr/bin/bwrap', '--die-with-parent']
    assert argv[argv.index('--bind') + 1:argv.index('--bind') + 3] == [str(private), str(private)]
    assert argv.count('--ro-bind') == 2
    assert argv[-1] == '--'


def test_probe_refuses_a_guard_that_allows_snapshot_writes(tmp_path):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'source.md').write_text('unchanged')
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        guards.probe_guard([], dict(os.environ), private, cwd, 'agent')


@pytest.mark.parametrize('provider', ['agent', 'agy'])
@pytest.mark.parametrize('version', ['2027.01.01-unseen', ''])
def test_version_is_optional_evidence_not_an_admission_rule(tmp_path, monkeypatch, provider, version):
    from cli_capabilities import discover
    binary = tmp_path / 'cli'
    binary.write_text(f"#!{sys.executable}\nimport sys\nif '--help' in sys.argv: print({HELP!r})\nelse: print({version!r}); sys.exit({0 if version else 1})\n")
    binary.chmod(0o700)
    metadata = {}
    discover(str(binary), dict(os.environ), str(tmp_path), provider=provider, prefix=[],
             required=['--mode', '--print'], values={'--mode': 'ask' if provider == 'agent' else 'plan'},
             metadata=metadata)
    assert metadata['version'] == (version or None)


@pytest.mark.parametrize('option', ['--print', '--mode', '--sandbox', '--model', '--output-format', '--workspace', '--trust'])
def test_each_required_cursor_option_is_checked_before_inference(tmp_path, monkeypatch, option):
    home = tmp_path / 'user'; auth_fixture(home)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('unchanged')
    missing_help = '\n'.join(line for line in HELP.splitlines() if not line.lstrip().startswith(option + ' '))
    binary = tmp_path / 'agent'
    binary.write_text(f"#!{sys.executable}\nimport sys\nif '--help' in sys.argv: print({missing_help!r})\nelif '--version' in sys.argv: print('new')\nelse: raise AssertionError('inference forbidden')\n")
    binary.chmod(0o700)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare('agent', str(binary), {'HOME': str(home)}, private, cwd,
                       dict(system_prompt='Review.', user_prompt='Version.', model='fixed'))
    assert error.value.detail == dict(provider='agent', stage='help', reason='required_option_missing', option=option)


def test_probe_refuses_a_guard_that_allows_only_host_writes(tmp_path):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'source.md').write_text('unchanged')
    # A subprocess double simulates successful snapshot protection but a host overwrite.
    from unittest.mock import patch
    def broken_probe(argv, **kwargs):
        Path(argv[-2]).write_text('FORBIDDEN')
        Path(argv[-1]).write_text('allowed')
        return subprocess.CompletedProcess(argv, 0)
    with patch.object(guards.subprocess, 'run', broken_probe):
        with pytest.raises(profiles.ProfileError) as error:
            guards.probe_guard([], dict(os.environ), private, cwd, 'agent')
    assert error.value.detail['reason'] == 'write_guard_probe_failed'


@pytest.mark.parametrize('provider', ['agent', 'agy'])
def test_router_failure_reports_the_concrete_cause_and_version_without_inference(tmp_path, monkeypatch, provider):
    import router
    import solar_state
    source, commit = repository(tmp_path)
    e = repo.build(repository=str(source), commit=commit, provider=provider, model='fixture-model',
                   instructions='Review the committed version.', rules=[])
    home = tmp_path / 'user'; auth_fixture(home); monkeypatch.setenv('HOME', str(home))
    for key in list(os.environ):
        if key.startswith(('SOLAR_ROUTER_' + provider.upper() + '_', 'SOLAR_AI_' + provider.upper() + '_')):
            monkeypatch.delenv(key)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    inference = tmp_path / 'inference-ran'
    help_text = '\n'.join(line for line in HELP.splitlines() if not line.lstrip().startswith('--print '))
    binary = tmp_path / provider
    binary.write_text(f'''#!{sys.executable}
import pathlib,sys
if '--version' in sys.argv: print('2027.02.02-renamed')
elif '--help' in sys.argv: print({help_text!r})
else: pathlib.Path({str(inference)!r}).write_text('ran')
''')
    binary.chmod(0o700)
    monkeypatch.setattr(PROVIDERS[provider], 'resolve_binary', lambda _: str(binary))
    fields = dict(provider=provider, execution_profile=repo.PROFILE,
                  access_policy=profiles.canonical(dict(version=1, mode='read', scopes=[str(source)], resources=[])),
                  review_input_manifest=profiles.canonical(e['manifest']), review_input_digest=e['review_input_digest'])
    with solar_state.session() as store:
        task = store.task_create([(k, json.dumps(v)) for k, v in fields.items()], 'Review.', status='queued')
        claim = store.task_claim_detail(task, 'reader')
    result = router.route(json.dumps(dict(text='x', provider=provider,
                                          execution=dict(task_id=task, token=claim['token'], profile=repo.PROFILE))))
    assert result['status'] == 'failed' and result['error_code'] == 'execution_profile_unsupported'
    assert result['error_detail'] == dict(provider=provider, stage='help', reason='required_option_missing', option='--print')
    assert result['review_preflight']['version'] == '2027.02.02-renamed'
    assert result['error'] == 'execution_profile_unsupported: help required_option_missing --print'
    assert not inference.exists()
    with solar_state.session() as store:
        row = [r for r in store.audit_rows(event='end') if r.get('task_id') == task][-1]
    assert row['error_detail'] == result['error_detail'] and row['review_preflight']['version'] == '2027.02.02-renamed'


def test_failure_after_preflight_still_reports_the_version(tmp_path, monkeypatch):
    import router
    import solar_state
    provider = 'agent'
    source, commit = repository(tmp_path)
    e = repo.build(repository=str(source), commit=commit, provider=provider, model='fixture-model',
                   instructions='Review the committed version.', rules=[])
    home = tmp_path / 'user'; auth_fixture(home); monkeypatch.setenv('HOME', str(home))
    for key in list(os.environ):
        if key.startswith(('SOLAR_ROUTER_AGENT_', 'SOLAR_AI_AGENT_')):
            monkeypatch.delenv(key)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    binary = tmp_path / provider
    binary.write_text(f'''#!{sys.executable}
import sys
if '--version' in sys.argv: print('2027.03.03-crashes')
elif '--help' in sys.argv: print({HELP!r})
else: sys.exit(3)
''')
    binary.chmod(0o700)
    monkeypatch.setattr(PROVIDERS[provider], 'resolve_binary', lambda _: str(binary))
    fields = dict(provider=provider, execution_profile=repo.PROFILE,
                  access_policy=profiles.canonical(dict(version=1, mode='read', scopes=[str(source)], resources=[])),
                  review_input_manifest=profiles.canonical(e['manifest']), review_input_digest=e['review_input_digest'])
    with solar_state.session() as store:
        task = store.task_create([(k, json.dumps(v)) for k, v in fields.items()], 'Review.', status='queued')
        claim = store.task_claim_detail(task, 'reader')
    result = router.route(json.dumps(dict(text='x', provider=provider,
                                          execution=dict(task_id=task, token=claim['token'], profile=repo.PROFILE))))
    assert result['status'] == 'failed'
    assert result['review_preflight']['version'] == '2027.03.03-crashes'
    with solar_state.session() as store:
        row = [r for r in store.audit_rows(event='end') if r.get('task_id') == task][-1]
    assert row['review_preflight']['version'] == '2027.03.03-crashes'


def test_each_refusal_cause_has_its_own_reason(tmp_path, monkeypatch):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    with pytest.raises(profiles.ProfileError) as error:
        guards.credential(tmp_path / 'missing', tmp_path / 'copy', 'agy')
    assert error.value.detail['reason'] == 'credentials_unavailable'
    monkeypatch.setattr(guards.sys, 'platform', 'linux')
    monkeypatch.setattr(guards.shutil, 'which', lambda *a, **k: None)
    with pytest.raises(profiles.ProfileError) as error:
        guards.guard_prefix(private, cwd, 'agent')
    assert (error.value.detail['reason'], error.value.detail['stage']) == ('boundary_unavailable', 'boundary')

    def hang(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 15)
    monkeypatch.setattr(guards.subprocess, 'run', hang)
    with pytest.raises(profiles.ProfileError) as error:
        guards.probe_guard([], dict(os.environ), private, cwd, 'agent')
    assert (error.value.detail['reason'], error.value.detail['stage']) == ('write_guard_probe_timeout', 'write_guard')


def test_present_managed_policy_is_reported_as_such(tmp_path, monkeypatch):
    home = tmp_path / 'user'; auth_fixture(home)
    (home / '.cursor' / 'managed').mkdir(parents=True)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare('agent', '/no-provider-should-run', {'HOME': str(home)}, private, cwd,
                       dict(system_prompt='Review.', user_prompt='Version.', model='fixed'))
    assert error.value.detail == dict(provider='agent', stage='managed_policy', reason='managed_policy_present')


@pytest.mark.parametrize('provider,option,value', [
    ('agent', '--mode', 'ask'), ('agent', '--sandbox', 'enabled'), ('agent', '--output-format', 'json'),
    ('agy', '--mode', 'plan'), ('agy', '--output-format', 'json')])
def test_each_value_solar_passes_must_be_advertised(tmp_path, monkeypatch, provider, option, value):
    home = tmp_path / 'user'; auth_fixture(home)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    help_text = '\n'.join(l.replace(value, 'other') if l.lstrip().startswith(option + ' ') else l for l in HELP.splitlines())
    binary = tmp_path / provider
    binary.write_text(f"#!{sys.executable}\nimport sys\nif '--help' in sys.argv: print({help_text!r})\nelse: raise AssertionError('inference forbidden')\n")
    binary.chmod(0o700)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare(provider, str(binary), {'HOME': str(home)}, private, cwd,
                       dict(system_prompt='Review.', user_prompt='Version.', model='fixed'))
    assert error.value.detail == dict(provider=provider, stage='help', reason='required_value_unadvertised', option=option)


@pytest.mark.parametrize('option', ['--print', '--mode', '--sandbox', '--model', '--output-format', '--disable-slash-commands', '--log-file'])
def test_each_required_agy_option_is_checked_before_inference(tmp_path, monkeypatch, option):
    home = tmp_path / 'user'; auth_fixture(home)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    missing_help = '\n'.join(l for l in HELP.splitlines() if not l.lstrip().startswith(option + ' '))
    binary = tmp_path / 'agy'
    binary.write_text(f"#!{sys.executable}\nimport sys\nif '--help' in sys.argv: print({missing_help!r})\nelse: raise AssertionError('inference forbidden')\n")
    binary.chmod(0o700)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare('agy', str(binary), {'HOME': str(home)}, private, cwd,
                       dict(system_prompt='Review.', user_prompt='Version.', model='fixed'))
    assert error.value.detail['reason'] == 'required_option_missing' and error.value.detail['option'] == option


def test_unknown_provider_is_reported_as_an_unsupported_profile(tmp_path):
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare('other', '/none', {'HOME': str(tmp_path)}, private, cwd,
                       dict(system_prompt='x', user_prompt='y', model='m'))
    assert error.value.detail == dict(provider='other', stage='profile', reason='provider_unsupported')


@pytest.mark.parametrize('raised,code', [('state', 'state_unavailable'), ('generic', 'provider_locked_failed')])
def test_other_failures_keep_the_preflight_in_result_and_audit(tmp_path, monkeypatch, raised, code):
    import router
    import solar_state
    source, commit = repository(tmp_path)
    e = repo.build(repository=str(source), commit=commit, provider='agent', model='fixture-model',
                   instructions='Review the committed version.', rules=[])
    adapter = PROVIDERS['agent']
    def run(*a, **k):
        adapter.last_review_preflight = dict(provider='agent', version='2027.04.04-x')
        raise solar_state.StateError('busy') if raised == 'state' else RuntimeError('boom')
    monkeypatch.setattr(adapter, 'run', run)
    fields = dict(provider='agent', execution_profile=repo.PROFILE,
                  access_policy=profiles.canonical(dict(version=1, mode='read', scopes=[str(source)], resources=[])),
                  review_input_manifest=profiles.canonical(e['manifest']), review_input_digest=e['review_input_digest'])
    with solar_state.session() as store:
        task = store.task_create([(k, json.dumps(v)) for k, v in fields.items()], 'Review.', status='queued')
        claim = store.task_claim_detail(task, 'reader')
    result = router.route(json.dumps(dict(text='x', provider='agent',
                                          execution=dict(task_id=task, token=claim['token'], profile=repo.PROFILE))))
    assert result['error_code'] == code
    assert result['review_preflight']['version'] == '2027.04.04-x'
    with solar_state.session() as store:
        row = [r for r in store.audit_rows(event='end') if r.get('task_id') == task][-1]
    assert row['review_preflight']['version'] == '2027.04.04-x'


FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('provider,fixture,stream', [
    ('agent', 'cursor_agent_2026.10.16_help.txt', 'stdout'),
    ('agy', 'agy_1.2.3_help_stderr.txt', 'stderr')])
def test_real_help_output_of_each_cli_passes_the_real_requirements(tmp_path, monkeypatch, provider, fixture, stream):
    """Captured from the installed CLIs with a throwaway HOME and no inference."""
    home = tmp_path / 'user'; auth_fixture(home)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    binary = tmp_path / provider
    binary.write_text(f"#!{sys.executable}\nimport sys\nif '--version' in sys.argv: print('9.9.9')\n"
                      f"elif '--help' in sys.argv: print(open({str(FIXTURES / fixture)!r}).read(), file=sys.{stream})\n"
                      "else: raise AssertionError('inference forbidden')\n")
    binary.chmod(0o700)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    metadata = {}
    argv, _ = guards.prepare(provider, str(binary), {'HOME': str(home)}, private, cwd,
                             dict(system_prompt='Review.', user_prompt='Version.', model='fixed'), metadata=metadata)
    assert metadata['version'] == '9.9.9' and '--print' in metadata['capabilities_checked']


@pytest.mark.parametrize('provider', ['agent', 'agy'])
def test_every_refusal_names_the_real_provider(tmp_path, monkeypatch, provider):
    home = tmp_path / 'user'
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    # No credentials in this fake home, and the macOS keychain fallback is simulated
    # as empty, so the test never reads the real keychain.
    monkeypatch.setattr(guards.subprocess, 'run', lambda argv, **k: subprocess.CompletedProcess(argv, 44, '', ''))
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare(provider, '/none', {'HOME': str(home)}, private, cwd,
                       dict(system_prompt='x', user_prompt='y', model='m'))
    assert error.value.detail['provider'] == provider and error.value.detail['reason'] == 'credentials_unavailable'
    monkeypatch.setattr(guards.sys, 'platform', 'linux')
    monkeypatch.setattr(guards.shutil, 'which', lambda *a, **k: None)
    with pytest.raises(profiles.ProfileError) as error:
        guards.guard_prefix(private, cwd, provider)
    assert error.value.detail['provider'] == provider
    monkeypatch.setattr(guards.subprocess, 'run', lambda argv, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 1)))
    with pytest.raises(profiles.ProfileError) as error:
        guards.probe_guard([], dict(os.environ), private, cwd, provider)
    assert error.value.detail['provider'] == provider


@pytest.mark.parametrize('provider', ['agent', 'agy'])
def test_prepare_passes_the_provider_to_the_boundary_and_probe_refusals(tmp_path, monkeypatch, provider):
    home = tmp_path / 'user'; auth_fixture(home)
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    manifest = dict(system_prompt='x', user_prompt='y', model='m')
    elsewhere = tmp_path / 'elsewhere'; elsewhere.mkdir()
    with pytest.raises(profiles.ProfileError) as error:  # snapshot not inside the private directory
        guards.prepare(provider, '/none', {'HOME': str(home)}, private, elsewhere, manifest)
    assert error.value.detail['provider'] == provider and error.value.detail['stage'] == 'boundary'
    private2 = tmp_path / 'private2'; private2.mkdir(); cwd2 = private2 / 'repository'; cwd2.mkdir()
    (cwd2 / 'file').write_text('x')
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards.subprocess, 'run', lambda argv, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 1)))
    with pytest.raises(profiles.ProfileError) as error:
        guards.prepare(provider, '/none', {'HOME': str(home)}, private2, cwd2, manifest)
    assert (error.value.detail['provider'], error.value.detail['reason']) == (provider, 'write_guard_probe_timeout')


def _prepare_without_model(tmp_path, monkeypatch, provider, help_text):
    home = tmp_path / 'user'; auth_fixture(home)
    guards.write_json(home / '.cursor/cli-config.json', dict(
        model=dict(modelId='default', displayName='Auto'), selectedModel=dict(modelId='default', parameters=[]),
        modelParameters={}, authInfo=dict(email='x@example.test'), hooks=dict(evil=1)))
    private = tmp_path / 'private'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
    (cwd / 'file').write_text('x')
    binary = tmp_path / provider
    binary.write_text(f"#!{sys.executable}\nimport sys\nif '--help' in sys.argv: print({help_text!r})\nelse: raise AssertionError('inference forbidden')\n")
    binary.chmod(0o700)
    monkeypatch.setattr(guards, 'guard_prefix', lambda *a: [])
    monkeypatch.setattr(guards, 'probe_guard', lambda *a: None)
    metadata = {}
    argv, env = guards.prepare(provider, str(binary), {'HOME': str(home)}, private, cwd,
                               dict(system_prompt='Review.', user_prompt='Version.', model=None), metadata=metadata)
    return argv, env, metadata


@pytest.mark.parametrize('provider', ['agent', 'agy'])
def test_without_a_model_none_is_passed_and_the_option_is_not_required(tmp_path, monkeypatch, provider):
    no_model_help = '\n'.join(l for l in HELP.splitlines() if not l.lstrip().startswith('--model '))
    argv, env, metadata = _prepare_without_model(tmp_path, monkeypatch, provider, no_model_help)
    assert '--model' not in argv
    assert '--model' not in metadata['capabilities_checked']


def test_cursor_without_a_model_reuses_only_the_model_choice_of_the_client(tmp_path, monkeypatch):
    argv, env, _ = _prepare_without_model(tmp_path, monkeypatch, 'agent', HELP)
    config = json.loads((Path(env['HOME']) / '.cursor/cli-config.json').read_text())
    assert config['model']['displayName'] == 'Auto' and config['selectedModel']['modelId'] == 'default'
    assert 'authInfo' not in config and 'hooks' not in config
    assert config['permissions']['deny'] == ['Write(**)', 'Shell(*)', 'Mcp(*:*)', 'WebFetch(*)']


def test_agy_keeps_a_private_log_for_the_failure_reason(tmp_path, monkeypatch):
    argv, env, _ = _prepare_without_model(tmp_path, monkeypatch, 'agy', HELP)
    log = Path(argv[argv.index('--log-file') + 1])
    assert Path(env['HOME']).parent in log.parents


def _long_review_root():
    return '/var/folders/' + ('y' * 30) + '/T/solar-repository-review-abcdefgh'


def test_a_long_macos_temp_makes_cursor_fall_back_outside_the_guard():
    root = _long_review_root()
    path = guards.cursor_project_path(root + '/repository',
                                      data_dir=root + '/home/cursor-data',
                                      tmpdir=root + '/tmp')
    assert path.startswith('/tmp/.cursor')
    with pytest.raises(profiles.ProfileError) as error:
        guards.require_cursor_state_inside(
            {'CURSOR_DATA_DIR': root + '/home/cursor-data', 'TMPDIR': root + '/tmp'},
            root + '/repository', Path('/tmp/sr-short'))
    assert error.value.detail['reason'] == 'cursor_project_path_outside_write_guard'


_CURSOR_PATH_FIXTURE = """
function s(t){return t.replace(/[^a-zA-Z0-9]/g,"-").replace(/-+/g,"-").replace(/^-+|-+$/g,"")}
function c(){const t=process.env.CURSOR_DATA_DIR;return t?.trim()?t:(0,i.join)((0,s.homedir)(),".cursor")}
function u(){return(0,i.join)(c(),"projects")}
function d(t){let e=u();e.length>83&&(e=c(),e.length>83&&(e=function(t){const e=(0,i.join)(t,".cursor");return e.length<=83?e:(0,i.join)("/tmp",".cursor")}((0,s.tmpdir)())));const r=(0,i.join)(e,(0,a.r_)(t));if(r.length>91){const t=(0,n.createHash)("sha256").update(r).digest("hex").substring(0,7);return`${r.substring(0,Math.min(83,r.length))}-${t}`}return r}
"""


def test_cursor_project_path_matches_a_cli_bundle_and_a_changed_limit_does_not(tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    bundle = tmp_path / 'index.js'
    bundle.write_text(_CURSOR_PATH_FIXTURE)
    node_bin = tmp_path / 'node'
    node_bin.symlink_to(node)
    workspace = '/tmp/sr-abcdefgh/repository'
    data = '/tmp/sr-abcdefgh/home/cursor-data'
    tmp = '/tmp/sr-abcdefgh/tmp'
    observed = guards.observe_cursor_project_path(bundle, workspace, data_dir=data, tmpdir=tmp)
    assert observed == guards.cursor_project_path(workspace, data_dir=data, tmpdir=tmp)
    long_workspace = '/var/folders/' + ('y' * 40) + '/T/solar-repository-review-abcdefgh/repository'
    long_data = '/var/folders/' + ('y' * 40) + '/T/solar-repository-review-abcdefgh/home/cursor-data'
    long_tmp = '/var/folders/' + ('y' * 40) + '/T/solar-repository-review-abcdefgh/tmp'
    observed = guards.observe_cursor_project_path(bundle, long_workspace, data_dir=long_data, tmpdir=long_tmp)
    assert Path(observed).resolve() == Path(guards.cursor_project_path(long_workspace, data_dir=long_data, tmpdir=long_tmp)).resolve()
    bundle.write_text(_CURSOR_PATH_FIXTURE.replace('e.length>83', 'e.length>10'))
    medium_workspace, medium_data, medium_tmp = '/tmp/ws', '/tmp/' + ('d' * 20), '/tmp'
    with pytest.raises(profiles.ProfileError) as error:
        guards.require_cursor_project_path_current(bundle, medium_workspace, data_dir=medium_data, tmpdir=medium_tmp)
    assert error.value.detail['reason'] == 'cursor_project_path_drift'
    bundle.write_text('not a cursor bundle')
    with pytest.raises(profiles.ProfileError) as error:
        guards.observe_cursor_project_path(bundle, workspace, data_dir=data, tmpdir=tmp)
    assert error.value.detail['reason'] == 'cursor_project_path_shape_unknown'
    node_bin.unlink()
    node_bin.write_text('#!/bin/sh\nexit 1\n')
    node_bin.chmod(0o755)
    bundle.write_text(_CURSOR_PATH_FIXTURE)
    with pytest.raises(profiles.ProfileError) as error:
        guards.observe_cursor_project_path(bundle, workspace, data_dir=data, tmpdir=tmp)
    assert error.value.detail['reason'] == 'cursor_project_path_unreadable'


def test_cursor_path_observer_does_not_inherit_node_options(tmp_path, monkeypatch):
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    bundle = tmp_path / 'index.js'
    bundle.write_text(_CURSOR_PATH_FIXTURE)
    (tmp_path / 'node').symlink_to(node)
    marker = tmp_path / 'injected'
    hook = tmp_path / 'hook.js'
    hook.write_text('require("fs").writeFileSync(' + repr(str(marker)) + ', "x")\n')
    monkeypatch.setenv('NODE_OPTIONS', '--require ' + str(hook))
    workspace = '/tmp/sr-abcdefgh/repository'
    data = '/tmp/sr-abcdefgh/home/cursor-data'
    tmp = '/tmp/sr-abcdefgh/tmp'
    observed = guards.observe_cursor_project_path(bundle, workspace, data_dir=data, tmpdir=tmp)
    assert observed == guards.cursor_project_path(workspace, data_dir=data, tmpdir=tmp)
    assert not marker.exists()


def test_cursor_project_path_matches_the_installed_cli():
    agent = shutil.which('agent')
    index = Path(agent).resolve().parent / 'index.js' if agent else None
    if index is None or not index.is_file() or not (index.parent / 'node').is_file():
        pytest.skip('Cursor CLI bundle is not installed')
    workspace = '/tmp/sr-abcdefgh/repository'
    data = '/tmp/sr-abcdefgh/home/cursor-data'
    tmp = '/tmp/sr-abcdefgh/tmp'
    guards.require_cursor_project_path_current(Path(agent), workspace, data_dir=data, tmpdir=tmp)
    long_workspace = '/var/folders/' + ('y' * 40) + '/T/solar-repository-review-abcdefgh/repository'
    long_data = '/var/folders/' + ('y' * 40) + '/T/solar-repository-review-abcdefgh/home/cursor-data'
    long_tmp = '/var/folders/' + ('y' * 40) + '/T/solar-repository-review-abcdefgh/tmp'
    guards.require_cursor_project_path_current(Path(agent), long_workspace, data_dir=long_data, tmpdir=long_tmp)


def test_a_short_review_directory_keeps_cursor_state_inside_the_guard(monkeypatch):
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: '/var/folders/' + ('y' * 40) + '/T')
    with repo.review_directory() as private:
        assert str(private).startswith('/tmp/sr-')
        data = str(private / 'home' / 'cursor-data')
        tmp = str(private / 'tmp')
        workspace = private / 'repository'
        workspace.mkdir()
        path = guards.cursor_project_path(str(workspace), data_dir=data, tmpdir=tmp)
        Path(path).resolve().relative_to(private.resolve())
        assert not path.startswith('/tmp/.cursor')
        created = guards.finish_cursor_launch([], {'CURSOR_DATA_DIR': data, 'TMPDIR': tmp, 'PATH': os.environ.get('PATH', '')},
                                              private, workspace)
        assert Path(created).is_dir()


def test_mkdir_under_guard_does_not_import_the_snapshot(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    cwd = private / 'repository'
    cwd.mkdir()
    marker = private / 'hostile-imported'
    (cwd / 'pathlib.py').write_text(
        'import pathlib, sys\n'
        f'pathlib.Path({str(marker)!r}).write_text("imported")\n'
        'raise SystemExit(86)\n')
    target = private / 'home' / 'cursor-data' / 'projects' / 'ws'
    guards.mkdir_under_guard([], {'PATH': os.environ.get('PATH', '')}, cwd, str(target))
    assert target.is_dir()
    assert not marker.exists()


def _write_guard_helper():
    if sys.platform == 'darwin':
        return Path('/usr/bin/sandbox-exec').is_file()
    if sys.platform == 'linux':
        return shutil.which('bwrap', path='/usr/bin:/bin') is not None
    return False


@pytest.mark.skipif(not _write_guard_helper(), reason='OS write guard helper is not installed')
def test_finish_cursor_launch_mkdirs_under_the_os_write_guard(monkeypatch):
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: '/var/folders/' + ('y' * 40) + '/T')
    with repo.review_directory() as private:
        workspace = private / 'repository'
        workspace.mkdir()
        (workspace / 'source.md').write_text('unchanged')
        marker = private / 'hostile-imported'
        (workspace / 'pathlib.py').write_text(
            'import pathlib\n'
            f'pathlib.Path({str(marker)!r}).write_text("imported")\n'
            'raise SystemExit(86)\n')
        data = private / 'home' / 'cursor-data'
        tmp = private / 'tmp'
        data.mkdir(parents=True)
        tmp.mkdir()
        prefix = guards.guard_prefix(private, workspace, 'agent')
        created = guards.finish_cursor_launch(
            prefix,
            {'CURSOR_DATA_DIR': str(data), 'TMPDIR': str(tmp), 'PATH': os.environ.get('PATH', '')},
            private, workspace)
        assert Path(created).is_dir()
        Path(created).resolve().relative_to(private.resolve())
        assert not str(created).startswith('/tmp/.cursor')
        assert not marker.exists()
        assert (workspace / 'source.md').read_text() == 'unchanged'


def test_cursor_eperm_names_the_write_guard_instead_of_a_generic_provider_failure():
    from providers.base import raise_restricted_failure
    named = dict(provider='agent', stage='state', reason='cursor_project_path_outside_write_guard')
    with pytest.raises(profiles.ProfileError) as error:
        raise_restricted_failure('agent', "exit 1: Error: EPERM: operation not permitted, mkdir '/tmp/.cursor/x'", 1)
    assert error.value.detail == named
    with pytest.raises(profiles.ProfileError) as error:
        raise_restricted_failure('agent', "exit 1: Error: EPERM: operation not permitted, mkdir '/tmp/.[REDACTED]'", 1)
    assert error.value.detail == named
    with pytest.raises(RuntimeError, match='cursor-data'):
        raise_restricted_failure('agent', "exit 1: Error: EPERM: operation not permitted, mkdir '/x/home/cursor-data/projects/ws'", 1)
    with pytest.raises(RuntimeError, match='/tmp/other'):
        raise_restricted_failure('agent', "exit 1: Error: EPERM: operation not permitted, mkdir '/tmp/other'", 1)
    with pytest.raises(RuntimeError, match='not_logged_in'):
        raise_restricted_failure('agent', 'exit 1: not_logged_in', 1)
