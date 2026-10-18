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
    expected = 'Reviewed commit: ' + commit + '\n\nReview result'
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
