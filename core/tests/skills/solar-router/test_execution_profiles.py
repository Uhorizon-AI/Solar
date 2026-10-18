"""No real provider: executable doubles record both prompts, argv, env and cwd."""
import hashlib
import json
import os
from pathlib import Path
import sys
import pytest

import execution_profiles as profiles
import router
import solar_state
from providers import PROVIDERS
from review_inputs import create_parent


@pytest.fixture
def review(tmp_path, monkeypatch):
    source = tmp_path / 'source.txt'
    source.write_bytes('Approved café\r\n'.encode())
    envelope = profiles.build_review_envelope_v1(instructions='Find a contradiction.', rules=['Cite evidence.'],
        evidence=[dict(path=str(source), content=source.read_bytes().decode(),
                       sha256=hashlib.sha256(source.read_bytes()).hexdigest())], provider='claude', model='test-model')
    return source, envelope


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    # Doubles must never capture an inherited real inference credential.
    for key in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'):
        monkeypatch.setenv(key, 'test-only-not-a-credential')
    record = tmp_path / 'launch.json'
    binary = tmp_path / 'claude-double'
    binary.write_text(f'''#!{sys.executable}
import json, os, pathlib, stat, sys
if '--help' in sys.argv:
    print({repr(' '.join(profiles.FLAGS))})
else:
    pathlib.Path({str(record)!r}).write_text(json.dumps(dict(argv=sys.argv[1:], env=dict(os.environ), cwd=os.getcwd(), pgid=os.getpgrp(), files=os.listdir('.'), mode=stat.S_IMODE(os.stat('.').st_mode))))
    print(json.dumps(dict(result='<subtasks>untrusted text</subtasks>',usage=dict(input_tokens=12,output_tokens=4))))
''')
    binary.chmod(0o700)
    monkeypatch.setattr(PROVIDERS['claude'], 'resolve_binary', lambda _: str(binary))
    monkeypatch.setattr(profiles, '_effective_managed_policy', lambda *args: {})
    for key in list(os.environ):
        if key.startswith(('SOLAR_ROUTER_CLAUDE_', 'SOLAR_AI_CLAUDE_')):
            monkeypatch.delenv(key)
    return record


def kwargs(envelope):
    return dict(manifest=envelope['manifest'], expected=envelope['review_input_digest'], profile=profiles.PROFILE)


def test_run_and_stream_have_identical_restricted_inputs_and_environment(review, fake_cli, tmp_path, monkeypatch):
    _, envelope = review
    home = tmp_path / 'hostile-home'
    (home / '.claude').mkdir(parents=True)
    (home / 'CLAUDE.md').write_text('HOSTILE_MEMORY')
    (home / '.claude/settings.json').write_text(json.dumps(dict(hooks={'SessionStart':'HOSTILE_HOOK'},
        permissions={'defaultMode':'bypassPermissions'}, enabledPlugins={'HOSTILE_PLUGIN': True}, mcpServers={'HOSTILE_MCP':{}})))
    for name in ('CLAUDE_CODE_SETTINGS_JSON', 'CLAUDE_CODE_PLUGIN_DIR', 'CLAUDE_CODE_SYSTEM_PROMPT',
                 'ANTHROPIC_MODEL', 'NODE_OPTIONS', 'BASH_ENV', 'CLAUDE_CODE_CLIENT_DATA_URL'):
        monkeypatch.setenv(name, 'HOSTILE_ENV')
    monkeypatch.setenv('HOME', str(home))
    adapter = PROVIDERS['claude']
    assert adapter.run('ENRICHED_BODY_SENTINEL', review=kwargs(envelope)) == '<subtasks>untrusted text</subtasks>'
    first = json.loads(fake_cli.read_text())
    assert list(adapter.stream('ENRICHED_BODY_SENTINEL', review=kwargs(envelope))) == ['<subtasks>untrusted text</subtasks>']
    second = json.loads(fake_cli.read_text())
    assert first['argv'] == second['argv']
    assert first['env'] == second['env']
    assert first['files'] == second['files'] == [] and first['mode'] == second['mode'] == 0o700
    assert not Path(first['cwd']).exists() and not Path(second['cwd']).exists()
    assert first['pgid'] == second['pgid'] == os.getpgrp()
    argv = first['argv']
    assert argv[argv.index('--system-prompt') + 1].encode() == envelope['manifest']['system_prompt'].encode()
    assert argv[-1].encode() == envelope['manifest']['user_prompt'].encode()
    assert argv[argv.index('--tools') + 1] == argv[argv.index('--setting-sources') + 1] == ''
    assert json.loads(argv[argv.index('--mcp-config') + 1]) == {'mcpServers': {}}
    assert json.loads(argv[argv.index('--settings') + 1]) == {'disableAllHooks': True}
    assert not set(argv) & {'--bare', '--resume', '--continue', '--append-system-prompt', '--add-dir', 'bypassPermissions'}
    assert 'HOSTILE_ENV' not in first['env'].values()
    assert 'ENRICHED_BODY_SENTINEL' not in ''.join(argv)
    assert adapter.last_usage == {'input_tokens': 12, 'output_tokens': 4}


@pytest.mark.parametrize('key', ['SOLAR_ROUTER_CLAUDE_CMD', 'SOLAR_AI_CLAUDE_CMD',
                               'SOLAR_ROUTER_CLAUDE_EXTRA_FLAGS', 'SOLAR_AI_CLAUDE_ARGS'])
@pytest.mark.parametrize('stream', [False, True])
def test_overrides_rejected_before_start(review, fake_cli, monkeypatch, key, stream):
    monkeypatch.setenv(key, '--tools Bash')
    adapter = PROVIDERS['claude']
    with pytest.raises(profiles.ProfileError, match='execution_profile_override_rejected'):
        list(adapter.stream('', review=kwargs(review[1]))) if stream else adapter.run('', review=kwargs(review[1]))
    assert not fake_cli.exists()


@pytest.mark.parametrize('provider', ['codex', 'agent', 'agy'])
@pytest.mark.parametrize('stream', [False, True])
def test_other_adapters_reject_without_binary_or_fallback(review, monkeypatch, provider, stream):
    adapter = PROVIDERS[provider]
    monkeypatch.setattr(adapter, 'resolve_binary', lambda _: pytest.fail('resolved unsupported provider'))
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        list(adapter.stream('', review=kwargs(review[1]))) if stream else adapter.run('', review=kwargs(review[1]))


@pytest.mark.parametrize('policy', [None, {'hooks': {'SessionStart': 'bad'}}, {'env': {'NODE_OPTIONS': 'bad'}},
                                  {'permissions': {'defaultMode': 'bypassPermissions'}}, {'managedMcpServers': {'x': {}}}])
def test_effective_policy_unknown_or_hostile_is_unsupported(review, fake_cli, monkeypatch, policy):
    monkeypatch.setattr(profiles, '_effective_managed_policy', lambda *args: policy)
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        PROVIDERS['claude'].run('', review=kwargs(review[1]))
    assert not fake_cli.exists()


def _preflight_reason(monkeypatch, runner, policy=None):
    """The reason a preflight failure carries; the code stays execution_profile_unsupported."""
    monkeypatch.setattr(profiles.subprocess, 'run', runner)
    if policy is not None:
        monkeypatch.setattr(profiles, '_effective_managed_policy', policy)
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported') as caught:
        profiles.preflight('claude-double', {}, '.')
    assert caught.value.code == 'execution_profile_unsupported'
    return caught.value.reason


def _timeout(*a, **k):
    raise profiles.subprocess.TimeoutExpired('claude', 10)


def _missing(*a, **k):
    raise FileNotFoundError('claude')


def _result(returncode, stdout):
    return lambda *a, **k: type('Result', (), {'returncode': returncode, 'stdout': stdout})()


def test_preflight_reasons_name_the_failed_help_check(monkeypatch):
    assert _preflight_reason(monkeypatch, _timeout) == 'help_timeout'
    assert _preflight_reason(monkeypatch, _missing) == 'help_unavailable'
    assert _preflight_reason(monkeypatch, _result(1, ' '.join(profiles.FLAGS))) == 'help_failed'
    assert _preflight_reason(monkeypatch, _result(0, '--print')) == 'help_missing_flags'


def test_preflight_reasons_name_the_failed_policy_check(monkeypatch, tmp_path):
    ok_help = _result(0, ' '.join(profiles.FLAGS))
    monkeypatch.setattr(profiles, '_local_managed_policy', lambda: None)
    assert _preflight_reason(monkeypatch, ok_help, profiles._effective_managed_policy) == 'policy_local_unreadable'
    monkeypatch.setattr(profiles, '_local_managed_policy', lambda: {'hooks': {}})
    assert _preflight_reason(monkeypatch, ok_help) == 'policy_local_present'
    monkeypatch.setattr(profiles, '_local_managed_policy', lambda: {})
    doctor = {}

    def runner(argv, **kw):
        if argv[1] == '--help':
            return ok_help()
        return doctor['run'](argv, **kw)
    for name, run, expected in (('timeout', _timeout, 'doctor_timeout'), ('missing', _missing, 'doctor_unavailable'),
                                ('failed', _result(1, ''), 'doctor_failed'),
                                ('unrecognized', _result(0, 'Managed settings (remote): fetched'), 'doctor_unrecognized')):
        doctor['run'] = run
        assert _preflight_reason(monkeypatch, runner) == expected, name


def test_doctor_accepting_an_account_without_organization_policy_has_no_reason(monkeypatch):
    ok = _result(0, 'Managed settings (remote): not fetched - Pro\nOrganization policy: not applicable to Pro\n')
    monkeypatch.setattr(profiles.subprocess, 'run', ok)
    assert profiles._doctor_check('claude-double', {}, '.') is None
    assert profiles._doctor_reports_no_org_policy('claude-double', {}, '.') is True


def test_failure_reason_reaches_the_error_message_without_changing_the_code(review, fake_cli, monkeypatch):
    source, envelope = review
    access = dict(version=1, mode='read', scopes=[str(source)], resources=[])
    values = dict(provider='claude', execution_profile=profiles.PROFILE, access_policy=profiles.canonical(access),
                  review_input_manifest=profiles.canonical(envelope['manifest']),
                  review_input_digest=envelope['review_input_digest'])
    with solar_state.session() as store:
        task = store.task_create([(k, json.dumps(v)) for k, v in values.items()], 'Review', status='queued')
        claimed = store.task_claim_detail(task, 'reader')
    payload = dict(provider='claude', execution=dict(task_id=task, token=claimed['token'], profile=profiles.PROFILE))
    monkeypatch.setattr(profiles.subprocess, 'run', _timeout)
    result = router.route(json.dumps(payload))
    assert result['error_code'] == 'execution_profile_unsupported'
    assert result['error'] == 'execution_profile_unsupported (help_timeout)'


def test_missing_cli_flag_is_unsupported(review, fake_cli, monkeypatch):
    monkeypatch.setattr(profiles.subprocess, 'run', lambda *a, **k: type('Result', (), {'returncode': 0, 'stdout':'--print'})())
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        PROVIDERS['claude'].run('', review=kwargs(review[1]))
    assert not fake_cli.exists()


def test_canonical_order_and_newlines_and_fixed_budget(review):
    _, envelope = review
    manifest = envelope['manifest']
    user = json.loads(manifest['user_prompt'])
    user['instructions'] = user['instructions'].replace('.', '.\r\n')
    user['instructions'] = user['instructions'].rstrip('\r\n')
    reversed_source = dict(reversed(list(user['evidence'][0].items())))
    user['evidence'] = [reversed_source]
    assert profiles.build_review_envelope_v1(provider='claude', model='test-model', **user) == envelope
    user['instructions'] = 'x' * profiles.MAX_INPUT_BYTES
    with pytest.raises(profiles.ProfileError, match='review_input_too_large'):
        profiles.build_review_envelope_v1(provider='claude', model='test-model', **user)


def bound_child(tmp_path):
    source = tmp_path / 'input.txt'
    source.write_text('captured evidence')
    with solar_state.session() as store:
        parent, token, declarations, catalog = create_parent(store, source)
        children = store.materialize_children(parent, declarations, token=token)
        store.task_await(parent, [c['id'] for c in children], token=token)
        child = children[0]['id']
        claimed = store.task_claim_detail(child, 'reader')
        assert claimed['claimed']
    raw = dict(request_id='audit-id', text='BODY_SENTINEL', channel='async-task', mode='direct_only',
               session_id='audit-session', metadata={'agent':'JIT_SENTINEL'}, provider='claude',
               execution=dict(task_id=child, token=claimed['token'], profile=profiles.PROFILE))
    return source, raw, catalog['reviews'][0]['manifest']


@pytest.mark.parametrize('stream', [False, True])
def test_restricted_router_never_loads_or_writes_interactive_context(tmp_path, monkeypatch, fake_cli, stream):
    _, payload, manifest = bound_child(tmp_path)
    sentinels = ['GLOBAL_SENTINEL', 'HISTORY_SENTINEL', 'JIT_SENTINEL', 'SYSTEM_SENTINEL', 'BODY_SENTINEL']
    # Distinct sentinels exist in every ambient source. Any loader/write is also fatal.
    system_file = router.SOLAR_WORKSPACE / 'sun/system_prompt.md'
    system_file.write_text(sentinels[3])
    monkeypatch.setattr(router, 'SYSTEM_PROMPT_FILE', system_file)
    with solar_state.session() as store:
        store.continuity_import_text(json.dumps({'active_task': sentinels[0]}) + '\n')
    conv = router.conversation_file('audit-session')
    conv.parent.mkdir(parents=True, exist_ok=True)
    conv.write_text(json.dumps({'role':'user','text':sentinels[1]}) + '\n')
    before = conv.read_bytes()
    for name in ('resolve_jit_context', 'read_system_prompt', 'conversation_context', 'load_continuity',
                 'touch_continuity_channel', 'build_prompt', 'append_message', 'save_summary', 'resolve_decision'):
        monkeypatch.setattr(router, name, lambda *a, _name=name, **k: pytest.fail(f'called {_name}'))
    if stream:
        events = [json.loads(line) for line in router.route_stream(json.dumps(payload))]
        result = events[-1]
        assert events[0]['type'] == 'chunk'
    else:
        result = router.route(json.dumps(payload))
    assert result['status'] == 'success', result
    record = json.loads(fake_cli.read_text())
    argv = record['argv']
    system, user = argv[argv.index('--system-prompt') + 1], argv[-1]
    assert system.encode() == manifest['system_prompt'].encode()
    assert user.encode() == manifest['user_prompt'].encode()
    assert not any(s in system + user for s in sentinels)
    assert conv.read_bytes() == before
    with solar_state.session() as store:
        assert store.continuity_get()['active_task'] == sentinels[0]
        assert len(store.task_list()) == 4  # <subtasks> in output was inert


@pytest.mark.parametrize('change', ['source', 'missing', 'manifest', 'profile', 'digest', 'token'])
@pytest.mark.parametrize('stream', [False, True])
def test_tampering_aborts_before_provider_and_releases_only_current_claim(tmp_path, fake_cli, change, stream):
    source, payload, _ = bound_child(tmp_path)
    child = payload['execution']['task_id']
    with solar_state.session() as store:
        if change == 'source':
            source.write_text('changed')
        elif change == 'missing':
            source.unlink()
        elif change == 'manifest':
            store.task_set(child, 'review_input_manifest', json.dumps('{}'))
        elif change == 'profile':
            store.task_set(child, 'execution_profile', json.dumps('different'))
        elif change == 'digest':
            store.task_set(child, 'review_input_digest', json.dumps('0' * 64))
        else:
            payload['execution']['token'] = 'stale-token'
    result = ([json.loads(line) for line in router.route_stream(json.dumps(payload))][-1]
              if stream else router.route(json.dumps(payload)))
    assert result['error_code'] == 'review_input_mismatch', result
    assert not fake_cli.exists()
    with solar_state.session() as store:
        assert store.task_status(child) == ('active' if change == 'token' else 'draft')
        assert bool(store.reservation_for(child)) == (change == 'token')


def test_change_after_preflight_is_detected_just_before_subprocess(tmp_path, fake_cli, monkeypatch):
    source, payload, _ = bound_child(tmp_path)
    original = profiles.preflight
    def change(*args):
        original(*args)
        source.write_text('changed during preflight')
    monkeypatch.setattr(profiles, 'preflight', change)
    assert router.route(json.dumps(payload))['error_code'] == 'review_input_mismatch'
    assert not fake_cli.exists()


def test_interactive_router_preserves_ambient_sentinels(tmp_path, monkeypatch):
    captured = []
    system_file = tmp_path / 'system_prompt.md'
    system_file.write_text('SYSTEM_SENTINEL')
    monkeypatch.setattr(router, 'SYSTEM_PROMPT_FILE', system_file)
    conv = router.conversation_file('interactive-sentinels')
    conv.parent.mkdir(parents=True, exist_ok=True)
    conv.write_text(json.dumps({'role':'user','text':'HISTORY_SENTINEL'}) + '\n')
    with solar_state.session() as store:
        store.continuity_import_text(json.dumps({'active_task':'GLOBAL_SENTINEL'}) + '\n')
    monkeypatch.setattr(router, 'run_strict_provider', lambda provider, prompt: (captured.append(prompt) or 'done', provider))
    result = router.route(json.dumps(dict(text='BODY_SENTINEL', session_id='interactive-sentinels',
        mode='direct_only', provider='claude', metadata={'agent':'JIT_SENTINEL'})))
    assert result['status'] == 'success'
    assert all(s in captured[0] for s in ['SYSTEM_SENTINEL','HISTORY_SENTINEL','GLOBAL_SENTINEL','JIT_SENTINEL','BODY_SENTINEL'])


@pytest.mark.parametrize('filename,document', [('.claude/settings.json', {'hooks': {'SessionStart':'bad'}}),
    ('.claude/settings.local.json', {'permissions': {'defaultMode':'bypassPermissions'}}),
    ('.mcp.json', {'mcpServers': {'bad': {}}}), ('.claude/settings.json', {'enabledPlugins': {'bad': True}})])
def test_project_overrides_rejected_before_help_or_launch(review, fake_cli, tmp_path, monkeypatch, filename, document):
    project = tmp_path / 'hostile-project'
    path = project / filename
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document))
    monkeypatch.setattr(PROVIDERS['claude'], 'get_cwd', lambda: project)
    monkeypatch.setattr(profiles, 'preflight', lambda *args: pytest.fail('override reached preflight'))
    with pytest.raises(profiles.ProfileError, match='execution_profile_override_rejected'):
        PROVIDERS['claude'].run('', review=kwargs(review[1]))
    assert not fake_cli.exists()


def test_extra_flags_cannot_change_the_constructor(review, fake_cli):
    with pytest.raises(profiles.ProfileError, match='execution_profile_override_rejected'):
        with profiles.restricted_launch(PROVIDERS['claude'], **kwargs(review[1]), extra_flags=['--tools','Bash']):
            pytest.fail('extra flags accepted')
    assert not fake_cli.exists()


def test_noncanonical_prompt_cannot_change_approved_bytes(review):
    manifest = dict(review[1]['manifest'])
    manifest['system_prompt'] = manifest['system_prompt'].replace('\n', '\r\n')
    with pytest.raises(profiles.ProfileError, match='review_input_mismatch'):
        profiles.verify_envelope(manifest, profiles.digest(manifest), provider='claude', profile=profiles.PROFILE)


def test_symlink_cannot_widen_approved_source_reads(review, tmp_path):
    source, envelope = review
    outside = tmp_path / 'outside'
    outside.write_bytes(source.read_bytes())
    original_scope = tmp_path / 'scoped'
    original_scope.mkdir()
    link = original_scope / 'source'
    link.symlink_to(outside)
    user = json.loads(envelope['manifest']['user_prompt'])
    user['evidence'][0]['path'] = str(link)
    manifest = profiles.build_review_envelope_v1(provider='claude', model='test-model', **user)['manifest']
    with pytest.raises(profiles.ProfileError, match='review_input_mismatch'):
        profiles.verify_sources(manifest, [str(original_scope)])


@pytest.mark.parametrize('provider', ['codex', 'agent', 'agy'])
@pytest.mark.parametrize('stream', [False, True])
def test_bound_router_never_falls_back_for_unsupported_provider(review, fake_cli, monkeypatch, provider, stream):
    source, envelope = review
    access = dict(version=1,mode='read',scopes=[str(source)],resources=[])
    values = dict(provider=provider,execution_profile=profiles.PROFILE,access_policy=profiles.canonical(access),
                  review_input_manifest=profiles.canonical(envelope['manifest']), review_input_digest=envelope['review_input_digest'])
    with solar_state.session() as store:
        task = store.task_create([(k,json.dumps(v)) for k,v in values.items()], 'Review', status='queued')
        claimed = store.task_claim_detail(task, 'reader')
    payload=dict(provider=provider,execution=dict(task_id=task,token=claimed['token'],profile=profiles.PROFILE))
    monkeypatch.setattr(router, 'run_with_fallback', lambda *a: pytest.fail('fallback invoked'))
    result=([json.loads(line) for line in router.route_stream(json.dumps(payload))][-1]
            if stream else router.route(json.dumps(payload)))
    assert result['error_code'] == 'execution_profile_unsupported'
    assert not fake_cli.exists()


def test_oversized_approved_envelope_rejected_without_trimming(review, fake_cli):
    source, envelope = review
    manifest = dict(envelope['manifest'])
    user = json.loads(manifest['user_prompt'])
    user['instructions'] = 'x' * profiles.MAX_INPUT_BYTES
    manifest['user_prompt'] = profiles.canonical(user) + '\n'
    values = dict(provider='claude',execution_profile=profiles.PROFILE,
                  access_policy=profiles.canonical(dict(version=1,mode='read',scopes=[str(source)],resources=[])),
                  review_input_manifest=profiles.canonical(manifest),review_input_digest=profiles.digest(manifest))
    with solar_state.session() as store:
        task=store.task_create([(k,json.dumps(v)) for k,v in values.items()], 'Review', status='queued')
        claimed=store.task_claim_detail(task,'reader')
    payload=dict(execution=dict(task_id=task,token=claimed['token'],profile=profiles.PROFILE))
    result=router.route(json.dumps(payload))
    assert result['error_code'] == 'review_input_too_large'
    assert not fake_cli.exists()
    with solar_state.session() as store:
        assert store.task_status(task)=='draft' and not store.reservation_for(task)


def test_large_accepted_input_fits_portable_cli_arguments(review, fake_cli):
    _, original = review
    user = json.loads(original['manifest']['user_prompt'])
    user['instructions'] = 'x' * (profiles.MAX_INPUT_BYTES - 2048)
    envelope = profiles.build_review_envelope_v1(provider='claude', model='test-model', **user)
    assert envelope['manifest']['context_budget']['input_utf8_bytes'] <= 96 * 1024
    assert PROVIDERS['claude'].run('', review=kwargs(envelope)) == '<subtasks>untrusted text</subtasks>'
    record = json.loads(fake_cli.read_text())
    assert max(len(arg.encode('utf-8')) for arg in record['argv']) < 128 * 1024


@pytest.mark.parametrize('stream', [False, True])
def test_a_busy_state_is_transient_and_never_withdraws_the_approval(tmp_path, fake_cli, monkeypatch, stream):
    source, payload, _ = bound_child(tmp_path)
    child = payload['execution']['task_id']

    def busy(self, *args, **kwargs):
        raise solar_state.StateBusy('state lock not granted in time (a cutover is running)')

    monkeypatch.setattr(solar_state.Session, 'execution_snapshot', busy)
    result = ([json.loads(line) for line in router.route_stream(json.dumps(payload))][-1]
              if stream else router.route(json.dumps(payload)))
    assert result['error_code'] == 'state_unavailable', result
    assert not result.get('claim_released')
    assert not fake_cli.exists()
    with solar_state.session() as store:
        task = store.task_get(child)
        assert store.task_status(child) == 'active' and store.reservation_for(child) is not None
        assert solar_state.approval_state(task['frontmatter'], task['body']) is None
