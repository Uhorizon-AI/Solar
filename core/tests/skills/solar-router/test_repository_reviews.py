"""Repository exploration, stable versions and fail-closed provider construction."""
import json
import os
from pathlib import Path
import sys

import pytest
import execution_profiles as profiles
import repository_reviews as repo
from providers import PROVIDERS
from git_review_fixture import repository, git


def envelope(root, commit, provider='claude'):
    return repo.build(repository=str(root), commit=commit, provider=provider, model='fixture-model',
                      instructions='Review both requirements and operations.', rules=['Cite sources.'])


def test_builder_edits_and_new_commits_do_not_change_the_approved_snapshot(tmp_path):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    (root / 'operations.md').write_text('Builder now supports six.\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'builder continues')
    original = profiles.verify_envelope(e['manifest'], e['review_input_digest'], provider='claude', profile=repo.PROFILE)
    out = tmp_path / 'review'; out.mkdir()
    repo.materialize(original, out)
    assert (out / 'operations.md').read_text() == 'The maximum batch is five.\n'
    assert (root / 'operations.md').read_text() == 'Builder now supports six.\n'
    assert not (out / '.git').exists()
    assert json.loads(original['user_prompt'])['commit'] == commit
    repo.verify_copy(original, out)
    (out / 'unapproved.txt').write_text('changed')
    with pytest.raises(profiles.ProfileError, match='repository_review_modified'):
        repo.verify_copy(original, out)


@pytest.mark.parametrize('name,symlink', [('.env', False), ('.codex/config.toml', False), ('.CoDeX/config.toml', False), ('escape', True)])
def test_unsafe_tree_is_rejected_without_running_project_hooks(tmp_path, name, symlink):
    root, _ = repository(tmp_path)
    target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to('/etc/passwd') if symlink else target.write_text('untrusted')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'unsafe tree')
    with pytest.raises(profiles.ProfileError, match='repository_review_unsafe_tree'):
        envelope(root, git(root, 'rev-parse', 'HEAD'))


def test_digest_scope_model_and_provider_cannot_be_changed(tmp_path):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    with pytest.raises(profiles.ProfileError):
        profiles.verify_sources(e['manifest'], [str(tmp_path / 'other')])
    e['manifest']['model'] = 'another-model'
    with pytest.raises(profiles.ProfileError):
        profiles.verify_envelope(e['manifest'], e['review_input_digest'], provider='claude', profile=repo.PROFILE)
    for provider in ('ollama', 'unknown'):
        with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
            envelope(root, commit, provider)


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_both_transports_share_commands_and_snapshot_then_clean_up(tmp_path, monkeypatch, provider):
    root, commit = repository(tmp_path)
    e = envelope(root, commit, provider)
    record = tmp_path / 'record.json'
    binary = tmp_path / provider
    binary.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
if '--help' in sys.argv:
 print({repr(' '.join(profiles.FLAGS) + ' --sandbox read-only --json --ephemeral --ignore-user-config --ignore-rules --output-schema --output-last-message')})
else:
 pathlib.Path({str(record)!r}).write_text(json.dumps(dict(argv=sys.argv[1:], cwd=os.getcwd(), env=dict(os.environ),
    operations=pathlib.Path('operations.md').read_text())))
 if {provider!r} == 'codex':
  print(json.dumps(dict(type='item.completed', item=dict(type='agent_message',text='Reading the evidence first.'))))
  pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(dict(review='Review result')))
  print(json.dumps(dict(type='turn.completed',usage=dict(input_tokens=11,output_tokens=3))))
 else: print(json.dumps(dict(result='Review result',usage=dict(input_tokens=11,output_tokens=3))))
''')
    binary.chmod(0o700)
    auth_home = tmp_path / 'auth-home'; auth_home.mkdir()
    (auth_home / 'auth.json').write_text('{"auth_mode":"chatgpt","tokens":{}}')
    monkeypatch.setenv('CODEX_HOME', str(auth_home))
    monkeypatch.setenv('NODE_OPTIONS', 'HOSTILE')
    for key in list(os.environ):
        if key.startswith(('SOLAR_ROUTER_' + provider.upper() + '_', 'SOLAR_AI_' + provider.upper() + '_')):
            monkeypatch.delenv(key)
    monkeypatch.setattr(profiles, '_effective_managed_policy', lambda *a: {})
    monkeypatch.setattr(repo, 'codex_preflight', lambda *a: None)
    adapter = PROVIDERS[provider]
    monkeypatch.setattr(adapter, 'resolve_binary', lambda _: str(binary))
    review = dict(manifest=e['manifest'], expected=e['review_input_digest'], profile=repo.PROFILE)
    expected = ('Reviewed commit: ' + commit + '\nRepository HEAD when the review finished: ' + commit
                + ' (same as the reviewed commit)\n\nReview result')
    assert adapter.run('UNAPPROVED CONTEXT', review=review) == expected
    first = json.loads(record.read_text())
    assert ''.join(adapter.stream('UNAPPROVED CONTEXT', review=review)) == expected
    second = json.loads(record.read_text())
    def stable(argv):  # each launch uses its own private directory
        import re
        return [re.sub(r'solar-repository-review-\w+', 'PRIVATE', a) for a in argv]
    assert stable(first['argv']) == stable(second['argv'])
    assert first['operations'] == 'The maximum batch is five.\n'
    assert not Path(first['cwd']).exists() and not Path(second['cwd']).exists()
    assert 'HOSTILE' not in first['env'].values()
    assert 'UNAPPROVED CONTEXT' not in ''.join(first['argv'])
    assert adapter.last_usage == dict(input_tokens=11,output_tokens=3)
    if provider == 'claude':
        assert first['argv'][first['argv'].index('--tools')+1] == 'Read,Glob,Grep'
        assert 'Bash' not in first['argv'] and 'Edit' not in first['argv']
    else:
        assert first['argv'][first['argv'].index('--sandbox')+1] == 'read-only'
        assert '--ignore-user-config' in first['argv']
        assert '--output-schema' in first['argv'] and '--output-last-message' in first['argv']
        assert not Path(first['env']['CODEX_HOME']).exists()
    assert (root / 'operations.md').read_text() == 'The maximum batch is five.\n'


LABEL = 'Repository HEAD when the review finished: '


def test_freshness_same_head(tmp_path):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    assert repo.freshness_line(e['manifest']) == LABEL + commit + ' (same as the reviewed commit)'


def test_freshness_newer_head_is_recorded_and_snapshot_digest_is_unchanged(tmp_path):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    (root / 'operations.md').write_text('Builder now supports six.\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'builder continues')
    head = git(root, 'rev-parse', 'HEAD').strip()
    assert repo.freshness_line(e['manifest']) == LABEL + head + ' (differs from the reviewed commit)'
    # Recording freshness is not part of the approved contract.
    assert profiles.verify_envelope(e['manifest'], e['review_input_digest'], provider='claude', profile=repo.PROFILE)


def test_freshness_detached_head_still_reports_the_commit(tmp_path):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    git(root, 'checkout', '-q', '--detach', commit)
    assert repo.freshness_line(e['manifest']).endswith('(same as the reviewed commit)')


@pytest.mark.parametrize('breakage', ['moved', 'no_git', 'nested_without_git', 'unborn', 'timeout', 'bad_manifest'])
def test_freshness_failures_are_unknown_and_never_raise(tmp_path, monkeypatch, breakage):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    manifest = e['manifest']
    if breakage == 'moved':
        root.rename(tmp_path / 'moved')
    elif breakage == 'no_git':
        import shutil
        shutil.rmtree(root / '.git')
    elif breakage == 'nested_without_git':
        # An enclosing repository must never be reported as the approved one.
        import shutil
        git(tmp_path, 'init', '-q')
        git(tmp_path, 'config', 'user.name', 'Fixture'); git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
        (tmp_path / 'outer.txt').write_text('outer'); git(tmp_path, 'add', 'outer.txt'); git(tmp_path, 'commit', '-qm', 'outer')
        shutil.rmtree(root / '.git')
    elif breakage == 'unborn':
        empty = tmp_path / 'empty'; empty.mkdir(); git(empty, 'init', '-q')
        manifest = dict(manifest, user_prompt=json.dumps(dict(repository=str(empty), commit=commit)))
    elif breakage == 'timeout':
        import subprocess

        def timed_out(*a, **kw):
            raise subprocess.TimeoutExpired('git', 20)
        monkeypatch.setattr(repo.subprocess, 'run', timed_out)
    else:
        manifest = dict(manifest, user_prompt='not json')
    assert repo.freshness_line(manifest) == LABEL + 'unknown'


def test_review_succeeds_with_unknown_freshness_and_model_prose_is_not_the_record(tmp_path, monkeypatch):
    root, commit = repository(tmp_path)
    e = envelope(root, commit)
    binary = tmp_path / 'claude'
    binary.write_text(f'''#!{sys.executable}
import json, sys
if '--help' in sys.argv: print({repr(' '.join(profiles.FLAGS))})
else: print(json.dumps(dict(result='HEAD is deadbeef, the version is stale.')))
''')
    binary.chmod(0o700)
    monkeypatch.setattr(profiles, '_effective_managed_policy', lambda *a: {})
    adapter = PROVIDERS['claude']
    monkeypatch.setattr(adapter, 'resolve_binary', lambda _: str(binary))
    review = dict(manifest=e['manifest'], expected=e['review_input_digest'], profile=repo.PROFILE)
    real = repo._git  # only the HEAD read fails; the approved-snapshot checks keep working

    def failing_head(repository, *args, **kw):
        if args == ('rev-parse', '--verify', '-q', 'HEAD'):
            raise repo._error()
        return real(repository, *args, **kw)
    monkeypatch.setattr(repo, '_git', failing_head)
    out = adapter.run('ctx', review=review)
    lines = out.split('\n')
    assert lines[0] == 'Reviewed commit: ' + commit
    assert lines[1] == LABEL + 'unknown'
    assert out.endswith('HEAD is deadbeef, the version is stale.')


def test_codex_unknown_effective_policy_is_refused(tmp_path):
    binary = tmp_path / 'codex'
    binary.write_text('#!/bin/sh\necho "{}"\n'); binary.chmod(0o700)
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        repo.codex_preflight(str(binary), dict(os.environ), str(tmp_path), [])


@pytest.mark.parametrize('change', [None, 'mcp', 'hooks', 'managed', 'approval', 'unknown'])
def test_codex_effective_policy_requires_known_isolated_configuration(tmp_path, change):
    checks = {'config.load': {'status':'ok','details':{'mcp servers':'0',
              'enabled feature flags':'shell_tool', 'configuration scope':'invocation config, including cloud-managed policy'}},
              'sandbox.helpers': {'details': {'approval policy':'Never', 'managed filesystem source':'none'}}}
    if change == 'mcp': checks['config.load']['details']['mcp servers'] = '1'
    elif change == 'hooks': checks['config.load']['details']['enabled feature flags'] = 'shell_tool, hooks'
    elif change == 'managed': checks['sandbox.helpers']['details']['managed filesystem source'] = 'policy'
    elif change == 'approval': checks['sandbox.helpers']['details']['approval policy'] = 'OnRequest'
    elif change == 'unknown': checks = {}
    binary = tmp_path / 'codex'
    binary.write_text(f"""#!{sys.executable}
import sys,json
if '--help' in sys.argv: print('--sandbox read-only --model --json --ephemeral --ignore-user-config --ignore-rules --output-schema --output-last-message')
else: print({json.dumps({'checks':checks})!r})
""")
    binary.chmod(0o700)
    if change is None:
        repo.codex_preflight(str(binary), dict(os.environ), str(tmp_path), [])
    else:
        with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
            repo.codex_preflight(str(binary), dict(os.environ), str(tmp_path), [])


@pytest.mark.parametrize('provider', ['claude','codex'])
@pytest.mark.parametrize('stream', [False,True])
def test_real_router_uses_bound_repository_profile_before_ambient_context(tmp_path, monkeypatch, provider, stream):
    import router
    import solar_state
    root,commit=repository(tmp_path)
    e=envelope(root,commit,provider)
    values=dict(provider=provider,execution_profile=repo.PROFILE,
                access_policy=profiles.canonical(dict(version=1,mode='read',scopes=[str(root)],resources=[])),
                review_input_manifest=profiles.canonical(e['manifest']),review_input_digest=e['review_input_digest'])
    with solar_state.session() as store:
        task=store.task_create([(k,json.dumps(v)) for k,v in values.items()],'Review the committed version.',status='queued')
        claim=store.task_claim_detail(task,'reader')
        assert claim['claimed']
    record=tmp_path/'called'
    binary=tmp_path/provider
    binary.write_text(f'''#!{sys.executable}
import json,pathlib,sys
if '--help' in sys.argv: print({repr(' '.join(profiles.FLAGS))})
else:
 pathlib.Path({str(record)!r}).write_text(pathlib.Path('operations.md').read_text())
 if {provider!r}=='codex':
  pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(dict(review='Bound review')))
  print(json.dumps(dict(type='turn.completed',usage=dict(input_tokens=5,output_tokens=2))))
 else: print(json.dumps(dict(result='Bound review',usage=dict(input_tokens=5,output_tokens=2))))
''')
    binary.chmod(0o700)
    auth=tmp_path/'credentials';auth.mkdir();(auth/'auth.json').write_text('{}')
    monkeypatch.setenv('CODEX_HOME',str(auth))
    for name in list(os.environ):
        if name.startswith(('SOLAR_ROUTER_'+provider.upper()+'_','SOLAR_AI_'+provider.upper()+'_')):
            monkeypatch.delenv(name)
    monkeypatch.setattr(PROVIDERS[provider],'resolve_binary',lambda _:str(binary))
    monkeypatch.setattr(profiles,'_effective_managed_policy',lambda *a:{})
    monkeypatch.setattr(repo,'codex_preflight',lambda *a:None)
    for loader in ['read_system_prompt','conversation_context','load_continuity','resolve_jit_context']:
        monkeypatch.setattr(router,loader,lambda *a,**k:pytest.fail('ambient context loaded'))
    payload=dict(text='UNAPPROVED',provider=provider,execution=dict(task_id=task,token=claim['token'],profile=repo.PROFILE))
    result=([json.loads(line) for line in router.route_stream(json.dumps(payload))][-1]
            if stream else router.route(json.dumps(payload)))
    assert result['status']=='success',result
    assert commit in result['reply_text']
    assert record.read_text()=='The maximum batch is five.\n'
    record.unlink()
    payload['execution']['token']='stale'
    result=router.route(json.dumps(payload))
    assert result['error_code']=='review_input_mismatch'
    assert not record.exists()


def _codex_review(monkeypatch, stdout, last_message, returncode=0):
    """Drive run_review for Codex with a simulated launch and process; no provider is executed."""
    import subprocess
    from contextlib import contextmanager
    from providers.base import BaseProvider
    seen = {}

    @contextmanager
    def fake_launch(*args, **kwargs):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'last-message.json'
            if last_message is not None:
                out.write_text(last_message)
            seen['out'] = out
            yield ['codex', '--output-last-message', str(out)], {}, temp

    monkeypatch.setattr(profiles, 'restricted_launch', fake_launch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, ''))
    adapter = PROVIDERS['codex']
    return adapter.run_review(manifest={}, expected='', profile='other_profile')


def _events(*items, completed=True, extra=()):
    lines = [json.dumps(dict(type='item.completed', item=dict(type='agent_message', text=t))) for t in items]
    lines += [json.dumps(e) for e in extra]
    if completed:
        lines.append(json.dumps(dict(type='turn.completed', usage=dict(input_tokens=1, output_tokens=1))))
    return '\n'.join(lines)


def test_codex_progress_without_final_structured_message_is_a_failure(monkeypatch):
    # Reproduces the pilot weakness: only a progress-looking message, turn completed.
    with pytest.raises(RuntimeError, match='no structured final review'):
        _codex_review(monkeypatch, _events('I will review the documents.'), 'I will review the documents.')


def test_codex_missing_final_file_is_a_failure(monkeypatch):
    with pytest.raises(RuntimeError, match='no structured final review'):
        _codex_review(monkeypatch, _events('I will review the documents.'), None)


def test_codex_progress_then_final_uses_only_the_final_structured_message(monkeypatch):
    out = _codex_review(monkeypatch, _events('Reading the evidence.', 'Checking rules.', '{"review":"Finding A"}'),
                        json.dumps(dict(review='Finding A')))
    assert out == 'Finding A'
    assert 'Reading' not in out and 'Checking' not in out


@pytest.mark.parametrize('final', ['', '   ', '[]', '{"review":""}', '{"review":"  "}', '{"review":3}',
                                   '{"text":"x"}', '{"review":"x","extra":1}', 'not json'])
def test_codex_invalid_final_shape_is_a_failure(monkeypatch, final):
    with pytest.raises(RuntimeError, match='no structured final review'):
        _codex_review(monkeypatch, _events('x'), final)


@pytest.mark.parametrize('extra', [[dict(type='error', message='x')], [dict(type='turn.failed', error=dict(message='x'))]])
def test_codex_failure_events_propagate_even_with_a_valid_file(monkeypatch, extra):
    with pytest.raises(RuntimeError, match='returned an error'):
        _codex_review(monkeypatch, _events('x', extra=extra, completed=False), json.dumps(dict(review='ok')))


def test_codex_requires_exactly_one_completed_turn(monkeypatch):
    good = json.dumps(dict(review='ok'))
    with pytest.raises(RuntimeError, match='no completed review'):
        _codex_review(monkeypatch, _events('x', completed=False), good)
    with pytest.raises(RuntimeError, match='more than one completed turn'):
        _codex_review(monkeypatch, _events('x') + '\n' + json.dumps(dict(type='turn.completed')), good)


def test_codex_nonzero_exit_and_malformed_events_are_failures(monkeypatch):
    good = json.dumps(dict(review='ok'))
    with pytest.raises(RuntimeError, match='non-zero'):
        _codex_review(monkeypatch, _events('x'), good, returncode=1)
    with pytest.raises(RuntimeError, match='malformed events'):
        _codex_review(monkeypatch, 'not jsonl', good)


def test_codex_argv_requests_schema_and_final_message_file(tmp_path, monkeypatch):
    root, commit = repository(tmp_path)
    e = envelope(root, commit, 'codex')
    auth = tmp_path / 'auth'; auth.mkdir(); (auth / 'auth.json').write_text('{}')
    monkeypatch.setenv('CODEX_HOME', str(auth))
    monkeypatch.setattr(repo, 'codex_preflight', lambda *a: None)
    monkeypatch.setattr(PROVIDERS['codex'], 'resolve_binary', lambda _: 'codex')
    with repo.launch(PROVIDERS['codex'], e['manifest'], e['review_input_digest'], lambda: None) as (argv, env, cwd):
        schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
        assert schema == repo.CODEX_REVIEW_SCHEMA
        out = Path(argv[argv.index('--output-last-message') + 1])
        assert out.parent != Path(cwd) and out.parent == Path(argv[argv.index('--output-schema') + 1]).parent
        assert not out.exists()


def test_codex_preflight_requires_output_flags(tmp_path):
    binary = tmp_path / 'codex'
    binary.write_text(f"#!{sys.executable}\nprint('--sandbox read-only --model --json --ephemeral --ignore-user-config --ignore-rules')\n")
    binary.chmod(0o700)
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        repo.codex_preflight(str(binary), dict(os.environ), str(tmp_path), [])


@pytest.mark.parametrize('argv', [['codex', '--output-last-message'], ['codex', '--output-last-message', '/nonexistent/dir/x.json']])
def test_codex_unreadable_or_valueless_final_message_path_fails_cleanly(monkeypatch, argv):
    import subprocess
    from contextlib import contextmanager

    @contextmanager
    def fake_launch(*args, **kwargs):
        yield argv, {}, '.'

    monkeypatch.setattr(profiles, 'restricted_launch', fake_launch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, _events('x'), ''))
    with pytest.raises(RuntimeError, match='no structured final review'):
        PROVIDERS['codex'].run_review(manifest={}, expected='', profile='other_profile')


def test_codex_non_utf8_final_message_file_fails_cleanly(monkeypatch):
    import subprocess
    import tempfile
    from contextlib import contextmanager

    @contextmanager
    def fake_launch(*args, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'last-message.json'
            out.write_bytes(b'\x80\xff')
            yield ['codex', '--output-last-message', str(out)], {}, temp

    monkeypatch.setattr(profiles, 'restricted_launch', fake_launch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, _events('x'), ''))
    with pytest.raises(RuntimeError, match='no structured final review'):
        PROVIDERS['codex'].run_review(manifest={}, expected='', profile='other_profile')


# --- Opt-in Codex review evidence (simulated provider; nothing is executed) ---

GOOD_FINAL = json.dumps(dict(review='Finding A'))
SECRET = 'sk-live-0123456789abcdef0123456789'
COMMIT = 'a' * 40


def _evidence_run(monkeypatch, tmp_path, stdout, last_message, returncode=0, timeout=False, env=None):
    import subprocess
    from contextlib import contextmanager

    @contextmanager
    def fake_launch(*args, **kwargs):
        home = tmp_path / 'codex-home'
        home.mkdir(exist_ok=True)
        (home / 'auth.json').write_text(json.dumps(dict(tokens=dict(access_token=SECRET))))
        out = tmp_path / 'last-message.json'
        if last_message is not None:
            out.write_text(last_message)
        yield ['codex', '--output-last-message', str(out), '--model', 'fixture-model', '--', 'PROMPT-TEXT'], dict(CODEX_HOME=str(home), **(env or {})), str(tmp_path)

    def fake_run(*a, **k):
        if timeout:
            raise subprocess.TimeoutExpired(a, 1, output=stdout.encode())
        return subprocess.CompletedProcess(a, returncode, stdout, 'STDERR-TEXT')

    monkeypatch.setattr(profiles, 'restricted_launch', fake_launch)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    manifest = dict(user_prompt=json.dumps(dict(commit=COMMIT, task='PROMPT-TEXT')))
    return PROVIDERS['codex'].run_review(manifest=manifest, expected='', profile='other_profile')


def _runs(root):
    return sorted(p for p in Path(root).iterdir() if p.is_dir())


def test_evidence_is_off_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', '')
    before = set(tmp_path.iterdir())
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    # The simulated launch itself only creates these two entries; nothing else may appear.
    assert set(tmp_path.iterdir()) - before <= {tmp_path / 'codex-home', tmp_path / 'last-message.json'}


def test_evidence_when_enabled_keeps_private_redacted_copy_and_result_is_unchanged(monkeypatch, tmp_path):
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    stdout = _events('read auth ' + SECRET)
    assert _evidence_run(monkeypatch, tmp_path, stdout, GOOD_FINAL) == 'Finding A'
    (run,) = _runs(root)
    assert oct(root.stat().st_mode & 0o777) == '0o700' and oct(run.stat().st_mode & 0o777) == '0o700'
    assert sorted(p.name for p in run.iterdir()) == ['events.jsonl', 'last-message.json', 'meta.json']
    assert all(oct(p.stat().st_mode & 0o777) == '0o600' for p in run.iterdir())
    text = ''.join(p.read_text() for p in run.iterdir())
    assert SECRET not in text and 'PROMPT-TEXT' not in text and 'STDERR-TEXT' not in text
    assert '[REDACTED]' in (run / 'events.jsonl').read_text()
    assert (run / 'last-message.json').read_text() == GOOD_FINAL
    meta = json.loads((run / 'meta.json').read_text())
    assert meta['returncode'] == 0 and meta['model'] == 'fixture-model' and meta['commit'] == COMMIT
    assert 'user_prompt' not in meta


@pytest.mark.parametrize('kwargs,match', [
    (dict(returncode=1), 'non-zero'),
    (dict(stdout='not jsonl'), 'malformed events'),
    (dict(last_message=None), 'no structured final review'),
])
def test_evidence_survives_failures_and_failure_stays_failure(monkeypatch, tmp_path, kwargs, match):
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    args = dict(stdout=_events('x'), last_message=GOOD_FINAL)
    args.update(kwargs)
    with pytest.raises(RuntimeError, match=match):
        _evidence_run(monkeypatch, tmp_path, **args)
    (run,) = _runs(root)
    assert (run / 'events.jsonl').exists()
    assert json.loads((run / 'meta.json').read_text())['last_message_present'] is (args['last_message'] is not None)


def test_evidence_is_kept_on_timeout_and_timeout_still_raises(monkeypatch, tmp_path):
    import subprocess
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    with pytest.raises(subprocess.TimeoutExpired):
        _evidence_run(monkeypatch, tmp_path, _events('partial'), None, timeout=True)
    (run,) = _runs(root)
    assert json.loads((run / 'meta.json').read_text())['timed_out'] is True


@pytest.mark.parametrize('make', ['file', 'readonly', 'relative'])
def test_unwritable_evidence_directory_never_changes_the_outcome(monkeypatch, tmp_path, make):
    if make == 'file':
        target = tmp_path / 'blocked'
        target.write_text('x')
    elif make == 'readonly':
        parent = tmp_path / 'ro'
        parent.mkdir()
        parent.chmod(0o500)
        target = parent / 'evidence'
    else:
        target = 'relative/evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(target))
    try:
        assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
        with pytest.raises(RuntimeError, match='non-zero'):
            _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL, returncode=1)
    finally:
        if (tmp_path / 'ro').exists():
            (tmp_path / 'ro').chmod(0o700)


def test_symlinked_evidence_directory_is_refused(monkeypatch, tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(real)
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(link))
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    assert not list(real.iterdir())


def test_evidence_retention_is_bounded_and_spares_foreign_entries(monkeypatch, tmp_path):
    root = tmp_path / 'evidence'
    root.mkdir(mode=0o700)
    (root / 'notes.txt').write_text('mine')
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_KEEP', '2')
    import review_evidence
    for i in range(4):
        monkeypatch.setattr(review_evidence.time, 'strftime', lambda *a, i=i: '2026010%dT000000Z' % (i + 1))
        _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL)
    assert [p.name[:9] for p in _runs(root)] == ['20260103T', '20260104T']
    assert (root / 'notes.txt').read_text() == 'mine'


def test_evidence_files_are_size_capped(monkeypatch, tmp_path):
    import review_evidence
    monkeypatch.setattr(review_evidence, 'MAX_FILE_BYTES', 50)
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    _evidence_run(monkeypatch, tmp_path, _events('x' * 500), GOOD_FINAL)
    (run,) = _runs(root)
    assert (run / 'events.jsonl').stat().st_size == 50
    assert json.loads((run / 'meta.json').read_text())['events_truncated'] is True


def test_preexisting_directory_open_to_others_is_refused_and_left_untouched(monkeypatch, tmp_path):
    shared = tmp_path / 'shared'
    shared.mkdir()
    shared.chmod(0o755)
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(shared))
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    assert oct(shared.stat().st_mode & 0o777) == '0o755'
    assert not list(shared.iterdir())


def test_ssh_auth_sock_is_not_treated_as_a_secret_but_token_names_are(monkeypatch, tmp_path):
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    monkeypatch.setenv('SSH_AUTH_SOCK', '/private/tmp/agent.sock')
    monkeypatch.setenv('SERVICE_API_TOKEN', 'tok-value-12345')
    monkeypatch.setenv('TOKEN', 'bare-token-6789')
    monkeypatch.setenv('PASSWORD', 'bare-password-6789')
    _evidence_run(monkeypatch, tmp_path, _events('/private/tmp/agent.sock tok-value-12345 bare-token-6789 bare-password-6789'), GOOD_FINAL)
    (run,) = _runs(root)
    text = (run / 'events.jsonl').read_text()
    assert '/private/tmp/agent.sock' in text
    assert not any(v in text for v in ('tok-value-12345', 'bare-token-6789', 'bare-password-6789'))


def test_size_cap_never_splits_a_multibyte_character(monkeypatch, tmp_path):
    import review_evidence
    monkeypatch.setattr(review_evidence, 'MAX_FILE_BYTES', 50)
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    raw, cut = review_evidence._clean('\u00e9' * 100, [])
    assert cut and len(raw) <= 50
    raw.decode('utf-8')


def test_capture_failures_never_change_the_outcome_or_the_timeout(monkeypatch, tmp_path):
    import subprocess
    import review_evidence
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(tmp_path / 'evidence'))

    def boom(*a, **k):
        raise ImportError('broken')

    monkeypatch.setattr(review_evidence, 'capture_codex', boom)
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    with pytest.raises(subprocess.TimeoutExpired):
        _evidence_run(monkeypatch, tmp_path, _events('x'), None, timeout=True)


def test_closed_stderr_does_not_break_the_never_raises_contract(monkeypatch, tmp_path):
    import review_evidence
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', 'relative/evidence')

    class Broken:
        def write(self, *_):
            raise OSError('closed')

        def flush(self):
            raise OSError('closed')

    monkeypatch.setattr(review_evidence.sys, 'stderr', Broken())
    review_evidence.capture_codex(['codex'], {}, 'x', 0)


def test_restrictive_umask_still_leaves_a_writable_run_directory(monkeypatch, tmp_path):
    root = tmp_path / 'evidence'
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(root))
    import review_evidence
    original = review_evidence.capture_codex

    def under_umask(*args, **kwargs):  # only the capture runs masked; the simulated launch needs write bits
        old = os.umask(0o277)
        try:
            return original(*args, **kwargs)
        finally:
            os.umask(old)

    monkeypatch.setattr(review_evidence, 'capture_codex', under_umask)
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    (run,) = _runs(root)
    assert oct(run.stat().st_mode & 0o777) == '0o700'
    assert sorted(p.name for p in run.iterdir()) == ['events.jsonl', 'last-message.json', 'meta.json']


def test_unavailable_capture_module_warns_only_when_enabled(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, 'review_evidence', None)  # import raises ImportError
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    assert 'review evidence not captured: ModuleNotFoundError' in capsys.readouterr().err
    monkeypatch.setenv('SOLAR_ROUTER_REVIEW_EVIDENCE_DIR', '')
    assert _evidence_run(monkeypatch, tmp_path, _events('x'), GOOD_FINAL) == 'Finding A'
    assert capsys.readouterr().err == ''
