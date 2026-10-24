"""No real provider: executable doubles record both prompts, argv, env and cwd."""
import hashlib
import json
import os
from pathlib import Path
import sys
import pytest

import execution_profiles as profiles
import router
import runtime_views
import solar_state
from providers import PROVIDERS
from review_inputs import create_parent


REAL_POLICY = profiles._effective_managed_policy  # the fixture replaces it; this test needs the real one
HELP = Path(__file__).parent / 'fixtures' / 'claude_2.1.303_help.txt'


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
if '--version' in sys.argv:
    print('9.9.9 (Claude Code)')
elif '--help' in sys.argv:
    print(pathlib.Path({str(HELP)!r}).read_text())
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
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported') as caught:
        PROVIDERS['claude'].run('', review=kwargs(review[1]))
    # A reader that refuses without saying why still yields a fixed, named reason.
    assert caught.value.detail == dict(provider='claude', stage='policy', reason='policy_unknown')
    assert not fake_cli.exists()


def run_with_help(monkeypatch, review, text, *, version='9.9.9 (Claude Code)'):
    def fake(argv, **kwargs):
        out = version if '--version' in argv else text if '--help' in argv else json.dumps(dict(result='ok'))
        return type('Result', (), {'returncode': 0, 'stdout': out, 'stderr': ''})()
    monkeypatch.setattr(profiles.subprocess, 'run', fake)
    return PROVIDERS['claude'].run('', review=kwargs(review[1]))


def refusal(monkeypatch, review, text, **options):
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported') as caught:
        run_with_help(monkeypatch, review, text, **options)
    return caught.value.detail


def test_real_claude_help_declares_every_required_option():
    from cli_capabilities import advertised_values, option_blocks
    blocks = option_blocks(HELP.read_text())
    assert [flag for flag in profiles.FLAGS if flag not in blocks] == []
    assert 'json' in advertised_values(blocks['--output-format'])


@pytest.mark.parametrize('flag', profiles.FLAGS)
def test_option_missing_from_help_names_it_even_if_prose_mentions_it(review, fake_cli, monkeypatch, flag):
    # Only the declaration (shallow indent) is renamed; wrapped descriptions that start with the flag stay as prose.
    import re
    original = HELP.read_text().splitlines()
    declaration = re.compile(r'^( {0,4}(?:-[A-Za-z],\s+)?)' + re.escape(flag) + r'(?=[\s<,=\[]|$)')
    lines = [declaration.sub(r'\1--renamed-away', line) for line in original]
    assert sum(a != b for a, b in zip(original, lines)) == 1, f'exactly the {flag} declaration must change'
    text = '\n'.join(lines) + f'\nSee also {flag} in the docs.\n'
    detail = refusal(monkeypatch, review, text)
    assert detail == dict(provider='claude', stage='help', reason='required_option_missing', option=flag)
    assert not fake_cli.exists()


def test_output_format_json_must_be_advertised(review, fake_cli, monkeypatch):
    text = HELP.read_text().replace('"json"', '"xml"')
    detail = refusal(monkeypatch, review, text)
    assert detail == dict(provider='claude', stage='help', reason='required_value_unadvertised',
                          option='--output-format')


def test_version_never_decides_support(review, fake_cli, monkeypatch):
    adapter = PROVIDERS['claude']
    for version in ('0.0.1', '99.99.99 (Claude Code)'):
        assert run_with_help(monkeypatch, review, HELP.read_text(), version=version) is not None
        assert adapter.last_review_preflight['version'] == version


def test_unknown_help_format_is_named(review, fake_cli, monkeypatch):
    assert refusal(monkeypatch, review, 'no options here')['reason'] == 'help_format_unknown'


@pytest.mark.parametrize('error, reason', [(profiles.subprocess.TimeoutExpired('claude', 1), 'help_timeout'),
                                           (OSError('gone'), 'help_unavailable')])
def test_help_that_cannot_run_is_named(review, fake_cli, monkeypatch, error, reason):
    def fake(argv, **kwargs):
        if '--help' in argv:
            raise error
        return type('Result', (), {'returncode': 0, 'stdout': '1.0', 'stderr': ''})()
    monkeypatch.setattr(profiles.subprocess, 'run', fake)
    with pytest.raises(profiles.ProfileError) as caught:
        PROVIDERS['claude'].run('', review=kwargs(review[1]))
    assert caught.value.detail == dict(provider='claude', stage='help', reason=reason)


def test_help_with_nonzero_exit_is_named(review, fake_cli, monkeypatch):
    monkeypatch.setattr(profiles.subprocess, 'run', lambda argv, **k: type(
        'Result', (), {'returncode': 2, 'stdout': '', 'stderr': ''})())
    with pytest.raises(profiles.ProfileError) as caught:
        PROVIDERS['claude'].run('', review=kwargs(review[1]))
    assert caught.value.detail['reason'] == 'help_failed'


def test_policy_refusals_name_the_failed_check(review, fake_cli, monkeypatch):
    monkeypatch.setattr(profiles, '_effective_managed_policy', REAL_POLICY)
    monkeypatch.setattr(profiles, '_local_managed_policy', lambda: None)
    with pytest.raises(profiles.ProfileError) as caught:
        profiles.preflight(str(fake_cli.parent / 'claude-double'), {}, str(fake_cli.parent))
    assert caught.value.detail == dict(provider='claude', stage='policy', reason='policy_local_unreadable')
    monkeypatch.setattr(profiles, '_local_managed_policy', lambda: {'hooks': {}})
    with pytest.raises(profiles.ProfileError) as caught:
        profiles.preflight(str(fake_cli.parent / 'claude-double'), {}, str(fake_cli.parent))
    assert caught.value.detail['reason'] == 'policy_local_present'


@pytest.mark.parametrize('result, reason', [
    (profiles.subprocess.TimeoutExpired('claude', 1), 'doctor_timeout'),
    (OSError('gone'), 'doctor_unavailable'),
    ((3, ''), 'doctor_failed'),
    ((0, 'Something: else\n'), 'doctor_unrecognized'),
    ((0, 'Managed settings (remote): not fetched\nOrganization policy: not applicable\n'), None)])
def test_doctor_outcomes_have_fixed_reasons(result, reason, monkeypatch):
    def fake(argv, **kwargs):
        if isinstance(result, BaseException):
            raise result
        return type('Result', (), {'returncode': result[0], 'stdout': result[1], 'stderr': ''})()
    monkeypatch.setattr(profiles.subprocess, 'run', fake)
    assert profiles._doctor_check('claude', {}, '.') == reason


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


def restricted_start_channels(store):
    rows = store.conn.execute("SELECT json_extract(row, '$.channel') FROM audit "
                              "WHERE event = 'start' AND json_extract(row, '$.execution_profile') IS NOT NULL "
                              "ORDER BY seq").fetchall()
    return [row[0] for row in rows]


@pytest.mark.parametrize('given, expected', [
    ('async-task', 'async-task'), (' Telegram ', 'telegram'), (None, 'other'), ('', 'other'),
    ('bogus', 'other'), ('mcp', 'other'), ('absent', 'other')])
def test_restricted_start_channel_is_the_validated_payload_channel(tmp_path, fake_cli, given, expected):
    _, payload, _ = bound_child(tmp_path)
    if given == 'absent':
        payload.pop('channel')
    else:
        payload['channel'] = given
    assert router.route(json.dumps(payload))['status'] == 'success'
    with solar_state.session() as store:
        assert restricted_start_channels(store) == [expected]
        assert runtime_views.console_executions(store)['channels'] == [{'channel': expected, 'n': 1}]


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
        assert restricted_start_channels(store) == ['async-task']  # the payload's channel, not a hardcoded label
        assert runtime_views.console_executions(store)['channels'] == [{'channel': 'async-task', 'n': 1}]


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
def test_project_configuration_is_isolated_not_rejected(review, fake_cli, tmp_path, monkeypatch, filename, document):
    # The launch runs in an empty private temp directory with no setting sources, so workspace
    # configuration can never reach it: it must neither block the review nor leak into it.
    project = tmp_path / 'hostile-project'
    path = project / filename
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document))
    monkeypatch.setattr(PROVIDERS['claude'], 'get_cwd', lambda: project)
    # Nothing else may read the workspace either: record where the help and policy (`claude doctor`)
    # checks run.
    seen = []
    real_preflight = profiles.preflight

    def recording_preflight(binary, env, cwd, *rest):
        seen.append(('preflight', cwd))
        return real_preflight(binary, env, cwd, *rest)

    def recording_policy(binary, env, cwd, *rest):
        seen.append(('doctor', cwd))
        return {}

    monkeypatch.setattr(profiles, 'preflight', recording_preflight)
    monkeypatch.setattr(profiles, '_effective_managed_policy', recording_policy)
    assert PROVIDERS['claude'].run('', review=kwargs(review[1])) == '<subtasks>untrusted text</subtasks>'
    launched = json.loads(fake_cli.read_text())
    assert {kind for kind, _ in seen} == {'preflight', 'doctor'}
    assert {str(Path(cwd).resolve()) for _, cwd in seen} == {str(Path(launched['cwd']).resolve())}
    assert not str(launched['cwd']).startswith(str(project))
    assert launched['files'] == [] and launched['mode'] == 0o700
    argv = launched['argv']
    assert argv[argv.index('--setting-sources') + 1] == argv[argv.index('--tools') + 1] == ''
    assert {'--strict-mcp-config', '--safe-mode', '--restricted'} <= set(argv)
    assert json.loads(argv[argv.index('--mcp-config') + 1]) == {'mcpServers': {}}
    assert json.loads(argv[argv.index('--settings') + 1]) == {'disableAllHooks': True}
    assert str(project) not in ''.join(argv)


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
