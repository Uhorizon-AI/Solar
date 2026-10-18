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
 print({repr(' '.join(profiles.FLAGS) + ' --sandbox read-only --json --ephemeral --ignore-user-config --ignore-rules')})
else:
 pathlib.Path({str(record)!r}).write_text(json.dumps(dict(argv=sys.argv[1:], cwd=os.getcwd(), env=dict(os.environ),
    operations=pathlib.Path('operations.md').read_text())))
 if {provider!r} == 'codex':
  print(json.dumps(dict(type='item.completed', item=dict(type='agent_message',text='Review result'))))
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
    assert first['argv'] == second['argv']
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
if '--help' in sys.argv: print('--sandbox read-only --model --json --ephemeral --ignore-user-config --ignore-rules')
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
  print(json.dumps(dict(type='item.completed',item=dict(type='agent_message',text='Bound review'))))
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
