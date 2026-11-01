"""Offline release request and immutable post-merge publication contracts."""
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

MODULE = Path(__file__).resolve().parents[2] / 'scripts' / 'release_automation.py'
spec = importlib.util.spec_from_file_location('release_automation', MODULE)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
REPO = 'Example/Solar'
VERSION = 'v1.1.0'


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setenv('SOLAR_RELEASE_REPO', REPO)
    a.run('git', 'init', '-q', '-b', 'main')
    a.git('config', 'user.name', 'Fixture')
    a.git('config', 'user.email', 'fixture@example.invalid')
    a.git('remote', 'add', 'origin', f'https://github.com/{REPO}.git')
    cli = Path(a.CLI)
    cli.parent.mkdir(parents=True)
    cli.write_text('SOLAR_VERSION="1.0.0"\n')
    Path('CHANGELOG.md').write_text('## [1.0.0]\n- Old notes\n')
    Path('README.md').write_text(f'<!-- solar-bootstrap-pin -->\nhttps://raw.githubusercontent.com/{REPO}/v1.0.0/core/skills/solar-client/scripts/bootstrap_solar_client.sh\n<!-- /solar-bootstrap-pin -->')
    a.git('add', '.')
    a.git('commit', '-qm', 'feat: base')
    base = a.git('rev-parse', 'HEAD')
    a.git('switch', '-qc', f'release/{VERSION}')
    intent = {'schema': 1, 'version': VERSION, 'base_sha': base}
    Path('.github').mkdir()
    Path(a.INTENT).write_text(json.dumps(intent))
    cli.write_text('SOLAR_VERSION="1.1.0"\n')
    Path('CHANGELOG.md').write_text('## [1.1.0]\n- New notes\n\n## [1.0.0]\n- Old notes\n')
    Path('README.md').write_text(f'<!-- solar-bootstrap-pin -->\nhttps://raw.githubusercontent.com/{REPO}/{VERSION}/core/skills/solar-client/scripts/bootstrap_solar_client.sh\n<!-- /solar-bootstrap-pin -->')
    a.git('add', '.')
    a.git('commit', '-qm', 'chore(release): v1.1.0')
    head = a.git('rev-parse', 'HEAD')
    a.git('switch', '-q', 'main')
    a.git('merge', '--no-ff', '-qm', 'Merge release PR', f'release/{VERSION}')
    sha = a.git('rev-parse', 'HEAD')
    a.git('update-ref', 'refs/remotes/origin/main', sha)
    monkeypatch.setattr(a, 'live_registry', Mock(return_value={'schema': 1, 'paused': False, 'entries': []}))
    pr = {'number': 1, 'html_url': 'fixture-pr', 'merged_at': 'now', 'merge_commit_sha': sha,
          'base': {'ref': 'main', 'sha': base},
          'head': {'ref': f'release/{VERSION}', 'sha': head, 'repo': {'full_name': REPO}}}
    event = {'ref': 'refs/heads/main', 'after': sha, 'repository': {'full_name': REPO}}
    def pages(path):
        if path.endswith('/files'):
            return [{'filename': name} for name in a.ALLOWED]
        if '/commits/' in path:
            return [pr]
        return []
    monkeypatch.setattr(a, 'pages', Mock(side_effect=pages))
    monkeypatch.setattr(a, 'api', Mock(side_effect=AssertionError('Unexpected network request')))
    return {'base': base, 'head': head, 'sha': sha, 'pr': pr, 'event': event, 'intent': intent}


def test_verified_main_release(history):
    assert a.validate_event(REPO, history['event'], publish=True) == VERSION


def test_ordinary_inherited_intent_never_republishes(history):
    a.git('commit', '--allow-empty', '-qm', 'fix: ordinary change')
    event = {**history['event'], 'after': a.git('rev-parse', 'HEAD')}
    assert a.validate_event(REPO, event, publish=True) is None
    a.api.assert_not_called()


@pytest.mark.parametrize('field,value', [('ref', 'refs/heads/other'), ('after', '0' * 40), ('repository', {'full_name': 'Other/Repo'})])
def test_publisher_rejects_wrong_event(history, field, value):
    with pytest.raises(ValueError, match='exact main push SHA'):
        a.validate_event(REPO, {**history['event'], field: value}, publish=True)


@pytest.mark.parametrize('change', ['version', 'schema', 'base_sha', 'pin', 'changelog', 'code'])
def test_invalid_intent_metadata(history, change):
    intent = dict(history['intent'])
    if change in {'version', 'schema', 'base_sha'}:
        intent[change] = {'version': 'v1.0.0', 'schema': 2, 'base_sha': 'bad'}[change]
    elif change == 'pin':
        Path('README.md').write_text('wrong pin')
    elif change == 'changelog':
        Path('CHANGELOG.md').write_text('wrong notes')
    else:
        Path('unrelated.py').write_text('unexpected code')
    a.git('add', '.')
    a.git('commit', '--allow-empty', '-qm', 'mutate fixture')
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        a.check_metadata('HEAD', intent)


@pytest.mark.parametrize('field,value', [('merged_at', None), ('merge_commit_sha', '0' * 40), ('head', {'ref': 'release/v9.0.0', 'repo': {'full_name': REPO}})])
def test_publisher_needs_matching_merged_pr(history, field, value):
    history['pr'][field] = value
    with pytest.raises(ValueError, match='unique matching merged release PR'):
        a.validate_event(REPO, history['event'], publish=True)


def test_fork_cannot_request_publication(history):
    history['pr']['head']['repo']['full_name'] = 'Fork/Solar'
    with pytest.raises(ValueError, match='same-repository'):
        a.validate_event(REPO, {'pull_request': history['pr']})


def test_pr_with_code_cannot_publish(history, monkeypatch):
    monkeypatch.setattr(a, 'pages', lambda path: [{'filename': 'evil.py'}] if path.endswith('/files') else [history['pr']])
    with pytest.raises(ValueError, match='non-metadata'):
        a.validate_event(REPO, history['event'], publish=True)


@pytest.mark.parametrize('release', [None, {'tag_name': VERSION, 'draft': True}, {'tag_name': VERSION, 'prerelease': True}])
def test_unpublished_predecessor_blocks_next(history, monkeypatch, release):
    monkeypatch.setattr(a, 'api', lambda *args, **kwargs: release)
    with pytest.raises(ValueError, match='not published'):
        a.require_published(REPO, history['intent'])


def test_predecessor_tag_identity(history, monkeypatch):
    responses = [{'tag_name': VERSION}, {'object': {'type': 'commit', 'sha': history['head']}}]
    monkeypatch.setattr(a, 'api', Mock(side_effect=responses))
    a.require_published(REPO, history['intent'])
    responses = [{'tag_name': VERSION}, {'object': {'type': 'commit', 'sha': history['base']}}]
    monkeypatch.setattr(a, 'api', Mock(side_effect=responses))
    with pytest.raises(ValueError, match='does not match'):
        a.require_published(REPO, history['intent'])


def test_disabled_automerge_fails_before_any_push(history, monkeypatch):
    monkeypatch.setattr(a, 'api', lambda *args, **kwargs: {'allow_auto_merge': False, 'allow_merge_commit': True})
    with pytest.raises(ValueError, match='Enable Allow auto-merge'):
        a.repository_ready(REPO)
    assert not a.pages.called


def test_required_checks_cannot_be_bypassed(history, monkeypatch):
    monkeypatch.setattr(a, 'api', Mock(side_effect=[{'allow_auto_merge': True, 'allow_merge_commit': True}, {'contexts': []}]))
    with pytest.raises(ValueError, match='must be required'):
        a.repository_ready(REPO)


def test_origin_must_match_configured_repo(history):
    with pytest.raises(ValueError, match='origin must point'):
        a.require_remote('Other/Solar')


def test_squash_merge_pins_integrated_sha(history):
    a.git('reset', '--hard', history['base'])
    a.git('merge', '--squash', f'release/{VERSION}')
    a.git('commit', '-qm', 'squashed release')
    sha = a.git('rev-parse', 'HEAD')
    history['pr']['merge_commit_sha'] = sha
    assert sha != history['head']
    assert a.validate_event(REPO, {**history['event'], 'after': sha}, publish=True) == VERSION


def test_main_advance_does_not_retarget_release(history):
    pinned = history['sha']
    a.git('commit', '--allow-empty', '-qm', 'fix: later main')
    with pytest.raises(ValueError, match='exact main push SHA'):
        a.validate_event(REPO, history['event'], publish=True)
    a.git('checkout', '--detach', pinned)
    assert a.validate_event(REPO, history['event'], publish=True) == VERSION


def test_submit_reuses_pr_and_pins_head(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    monkeypatch.setattr(a, 'pages', lambda path: [history['pr']])
    commands = []
    real_run = a.run
    def run(*args):
        if args[0] == 'gh' or (args[0] == 'git' and args[1] == 'push'):
            commands.append(args)
            return ''
        return real_run(*args)
    monkeypatch.setattr(a, 'run', run)
    a.submit(REPO, VERSION)
    assert not any(cmd[:3] == ('gh', 'pr', 'create') for cmd in commands)
    merge = next(cmd for cmd in commands if cmd[:3] == ('gh', 'pr', 'merge'))
    assert '--auto' in merge and '--admin' not in merge
    assert merge[-2:] == ('--match-head-commit', history['head'])


def test_submit_blocks_other_release(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    other = {**history['pr'], 'head': {**history['pr']['head'], 'ref': 'release/v2.0.0'}}
    monkeypatch.setattr(a, 'pages', lambda path: [other])
    with pytest.raises(ValueError, match='Another release'):
        a.submit(REPO, VERSION)


def test_submit_creates_one_pr_before_requesting_automerge(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    monkeypatch.setattr(a, 'pages', lambda path: [])
    calls = []
    real_run = a.run
    def run(*args):
        if args[0] == 'gh' or (args[0] == 'git' and args[1] == 'push'):
            calls.append(args)
            if args[:3] == ('gh', 'pr', 'create'):
                body = Path(args[args.index('--body-file') + 1]).read_text()
                assert VERSION in body and history['head'] in body
                return 'fixture-pr'
            return ''
        return real_run(*args)
    monkeypatch.setattr(a, 'run', run)
    a.submit(REPO, VERSION)
    assert [cmd[:3] for cmd in calls] == [('git', 'push', '--no-follow-tags'), ('gh', 'pr', 'create'), ('gh', 'pr', 'merge')]


def test_resume_changed_head_never_pushes(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    history['pr']['head']['sha'] = '0' * 40
    monkeypatch.setattr(a, 'pages', lambda path: [history['pr']])
    with pytest.raises(ValueError, match='another head'):
        a.submit(REPO, VERSION)


def test_ordinary_publish_mode_has_no_publication_effect(history, monkeypatch, tmp_path):
    a.git('commit', '--allow-empty', '-qm', 'ordinary')
    event = {**history['event'], 'after': a.git('rev-parse', 'HEAD')}
    event_file = tmp_path / 'event.json'
    event_file.write_text(json.dumps(event))
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event_file))
    monkeypatch.setattr(a.sys, 'argv', ['release_automation.py', 'publish'])
    publish = Mock()
    real_run = a.subprocess.run
    def dispatch(args, *pos, **kwargs):
        if args[0] == 'bash':
            return publish(args, *pos, **kwargs)
        return real_run(args, *pos, **kwargs)
    monkeypatch.setattr(a.subprocess, 'run', dispatch)
    a.main()
    publish.assert_not_called()


def test_publish_delegates_only_verified_sha_version(history, monkeypatch, tmp_path):
    event_file = tmp_path / 'event.json'
    event_file.write_text(json.dumps(history['event']))
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event_file))
    monkeypatch.setattr(a.sys, 'argv', ['release_automation.py', 'publish'])
    publish = Mock()
    real_run = a.subprocess.run
    def dispatch(args, *pos, **kwargs):
        if args[0] == 'bash':
            return publish(args, *pos, **kwargs)
        return real_run(args, *pos, **kwargs)
    monkeypatch.setattr(a.subprocess, 'run', dispatch)
    a.main()
    assert publish.call_count == 1
    assert publish.call_args.args[0] == ['bash', 'core/scripts/create-release.sh', '--publish', '--version', VERSION]
    assert publish.call_args.kwargs['env']['SOLAR_RELEASE_INTERNAL_PUBLISH'] == history['sha']


def test_pr_rebase_keeps_publisher_on_new_integrated_sha(history):
    a.git('reset', '--hard', history['base'])
    a.git('commit', '--allow-empty', '-qm', 'ordinary newer main')
    parent = a.git('rev-parse', 'HEAD')
    a.git('cherry-pick', history['head'])
    sha = a.git('rev-parse', 'HEAD')
    history['pr']['merge_commit_sha'] = sha
    assert a.git('rev-parse', f'{sha}^') == parent
    assert a.validate_event(REPO, {**history['event'], 'after': sha}, publish=True) == VERSION


def test_main_code_advance_cannot_expand_authorized_request(history):
    a.git('reset', '--hard', history['base'])
    Path('ordinary.py').write_text('unrelated = True\n')
    a.git('add', 'ordinary.py')
    a.git('commit', '-qm', 'ordinary code on main')
    a.git('merge', '--no-ff', '-qm', 'merge release', f'release/{VERSION}')
    sha = a.git('rev-parse', 'HEAD')
    history['pr']['merge_commit_sha'] = sha
    with pytest.raises(ValueError, match='only release metadata'):
        a.validate_event(REPO, {**history['event'], 'after': sha}, publish=True)


def test_workflow_gates_and_permissions():
    workflow = MODULE.parents[2] / '.github' / 'workflows' / 'test-suite.yml'
    text = workflow.read_text()
    suites, publisher = text.split('\n  publish:', 1)
    assert 'contents: write' not in suites
    assert 'pull-requests: read' in suites
    assert 'checks: read' in publisher
    assert 'needs: suite' in publisher
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in publisher
    assert 'ref: ${{ github.sha }}' in publisher
    assert 'cancel-in-progress: false' in publisher and 'queue: max' in publisher
    assert 'release_automation.py publish' in publisher


def test_cli_code_changes_are_not_release_metadata(history):
    with open(a.CLI, 'a') as out:
        out.write('unexpected_code=true\n')
    a.git('add', a.CLI)
    a.git('commit', '-qm', 'unexpected CLI code')
    with pytest.raises(ValueError, match='not its code'):
        a.check_metadata('HEAD', history['intent'])


def test_readme_changes_outside_pin_are_not_release_metadata(history):
    with open('README.md', 'a') as out:
        out.write('\nUnexpected unrelated documentation')
    a.git('add', 'README.md')
    a.git('commit', '-qm', 'unexpected readme')
    with pytest.raises(ValueError, match='only the README'):
        a.check_metadata('HEAD', history['intent'])


def test_submission_from_actions_token_chain_is_refused(history, monkeypatch):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    with pytest.raises(ValueError, match='maintainer CLI'):
        a.repository_ready(REPO)


def omission_entry(history):
    return {'version': VERSION, 'request_sha': history['sha'], 'reason': 'Known defect; skip this allocated version',
            'runs': [55], 'evidence': {'writers_stopped': True, 'outcomes_reconciled': True,
                                    'notes': 'Operator reconciled all write outcomes and completed attempts.'}}


@pytest.fixture
def omission(history, monkeypatch):
    frozen = {'schema': 1, 'paused': True, 'entries': []}
    Path(a.OMISSIONS).write_text(json.dumps(frozen))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'freeze publication in protected recovery PR')
    parent = a.git('rev-parse', 'HEAD')
    after = {**frozen, 'entries': [omission_entry(history)]}
    Path(a.OMISSIONS).write_text(json.dumps(after))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'record reconciled omission')
    sha = a.git('rev-parse', 'HEAD')
    runs = [{'id': 55, 'head_sha': history['sha'], 'head_branch': 'main', 'event': 'push', 'status': 'completed'}]
    jobs = [{'id': 8, 'status': 'completed'}]
    monkeypatch.setattr(a, 'request_runs', Mock(return_value=runs))
    monkeypatch.setattr(a, 'object_pages', Mock(return_value=jobs))
    monkeypatch.setattr(a, 'api', Mock(return_value=None))
    return {'history': history, 'parent': parent, 'sha': sha, 'registry': after, 'runs': runs, 'jobs': jobs}


def test_reconciled_omission_accepts_failed_request_without_publication(omission):
    a.validate_registry_change(REPO, omission['parent'], omission['sha'])
    assert omission['registry']['entries'][0]['request_sha'] == omission['history']['sha']


@pytest.mark.parametrize('flag', ['writers_stopped', 'outcomes_reconciled'])
def test_uncertain_operator_evidence_blocks_omission(history, flag):
    entry = omission_entry(history)
    entry['evidence'][flag] = False
    with pytest.raises(ValueError, match='Unresolved writers'):
        a.check_registry({'schema': 1, 'paused': True, 'entries': [entry]})


def test_active_writer_run_blocks_omission(omission):
    omission['runs'][0]['status'] = 'in_progress'
    with pytest.raises(ValueError, match='still active'):
        a.validate_registry_change(REPO, omission['parent'], omission['sha'])


def test_unresolved_job_attempt_blocks_omission(omission):
    omission['jobs'][0]['status'] = 'queued'
    with pytest.raises(ValueError, match='job/attempt is unresolved'):
        a.validate_registry_change(REPO, omission['parent'], omission['sha'])


def test_all_request_runs_must_be_accounted_for(omission):
    omission['runs'].append({**omission['runs'][0], 'id': 56})
    with pytest.raises(ValueError, match='enumerate every'):
        a.validate_registry_change(REPO, omission['parent'], omission['sha'])


def test_published_release_cannot_be_classified_omitted(omission, monkeypatch):
    monkeypatch.setattr(a, 'api', Mock(return_value={'draft': False, 'tag_name': VERSION}))
    with pytest.raises(ValueError, match='was published'):
        a.validate_registry_change(REPO, omission['parent'], omission['sha'])


def test_correct_partial_tag_is_retained_during_omission(omission, monkeypatch):
    responses = [None, {'object': {'type': 'commit', 'sha': omission['history']['sha']}}]
    monkeypatch.setattr(a, 'api', Mock(side_effect=responses))
    a.validate_registry_change(REPO, omission['parent'], omission['sha'])


def test_conflicting_partial_tag_blocks_omission(omission, monkeypatch):
    responses = [None, {'object': {'type': 'commit', 'sha': omission['history']['base']}}]
    monkeypatch.setattr(a, 'api', Mock(side_effect=responses))
    with pytest.raises(ValueError, match='Partial tag identity conflicts'):
        a.validate_registry_change(REPO, omission['parent'], omission['sha'])


def test_omission_requires_separate_prior_freeze(history):
    Path(a.OMISSIONS).write_text(json.dumps({'schema': 1, 'paused': True, 'entries': [omission_entry(history)]}))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'invalid combined freeze/omit')
    with pytest.raises(ValueError, match='prior merged PR'):
        a.validate_registry_change(REPO, history['sha'], 'HEAD')


def test_omission_cannot_unfreeze_in_same_change(omission):
    data = {**omission['registry'], 'paused': False}
    Path(a.OMISSIONS).write_text(json.dumps(data))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'invalid combined omit/unfreeze')
    with pytest.raises(ValueError, match='do not unfreeze'):
        a.validate_registry_change(REPO, omission['parent'], 'HEAD')


def test_old_omissions_are_append_only(omission):
    changed = json.loads(json.dumps(omission['registry']))
    changed['entries'][0]['reason'] = 'silently rewritten'
    Path(a.OMISSIONS).write_text(json.dumps(changed))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'attempt rewrite')
    with pytest.raises(ValueError, match='append-only'):
        a.validate_registry_change(REPO, omission['sha'], 'HEAD')


@pytest.mark.parametrize('change', ['bad_sha', 'duplicate', 'bool_run', 'extra_field'])
def test_registry_schema_rejects_invalid_identity(history, change):
    entry = omission_entry(history)
    data = {'schema': 1, 'paused': True, 'entries': [entry]}
    if change == 'bad_sha':
        entry['request_sha'] = 'short'
    elif change == 'duplicate':
        data['entries'].append(dict(entry))
    elif change == 'bool_run':
        entry['runs'] = [True]
    else:
        entry['surprise'] = 'unknown field'
    with pytest.raises(ValueError):
        a.check_registry(data)


def test_live_omission_rejects_old_workflow_after_unfreeze(history, monkeypatch):
    data = {'schema': 1, 'paused': False, 'entries': [omission_entry(history)]}
    monkeypatch.setattr(a, 'live_registry', Mock(return_value=data))
    with pytest.raises(ValueError, match='permanently omitted'):
        a.guard_publication(REPO, VERSION, history['sha'])


def test_recovery_pause_blocks_unstarted_and_retry_writers(history, monkeypatch):
    monkeypatch.setattr(a, 'live_registry', Mock(return_value={'schema': 1, 'paused': True, 'entries': []}))
    with pytest.raises(ValueError, match='paused for recovery'):
        a.guard_publication(REPO, VERSION, history['sha'])
    with pytest.raises(ValueError, match='freeze blocks retries'):
        a.retry_remote(REPO, VERSION)


def test_verified_omission_allows_successor_without_publishing_defect(history, monkeypatch):
    data = {'schema': 1, 'paused': False, 'entries': [omission_entry(history)]}
    monkeypatch.setattr(a, 'live_registry', Mock(return_value=data))
    a.require_published(REPO, history['intent'])
    a.api.assert_not_called()


def test_omitted_predecessor_identity_must_match(history, monkeypatch):
    data = {'schema': 1, 'paused': False, 'entries': [{**omission_entry(history), 'request_sha': history['base']}]}
    monkeypatch.setattr(a, 'live_registry', Mock(return_value=data))
    with pytest.raises(ValueError, match='identity conflicts'):
        a.require_published(REPO, history['intent'])


def test_remote_retry_uses_exact_authorized_run_not_local_writer(history, monkeypatch):
    runs = [{'id': 55, 'head_sha': history['sha'], 'head_branch': 'main', 'event': 'push', 'status': 'completed', 'conclusion': 'failure'}]
    monkeypatch.setattr(a, 'request_runs', Mock(return_value=runs))
    calls = []
    original = a.run
    def run(*args):
        if args[0] == 'gh':
            calls.append(args)
            return ''
        return original(*args)
    monkeypatch.setattr(a, 'run', run)
    a.retry_remote(REPO, VERSION)
    assert calls == [('gh', 'run', 'rerun', '55', '--repo', REPO, '--failed')]
    a.request_runs.assert_called_once_with(REPO, history['sha'])


def test_remote_retry_refuses_active_run(history, monkeypatch):
    monkeypatch.setattr(a, 'request_runs', Mock(return_value=[{'id': 55, 'status': 'in_progress'}]))
    with pytest.raises(ValueError, match='active run'):
        a.retry_remote(REPO, VERSION)


def test_controlled_release_lifecycle_and_retry_use_real_writer_with_fake_services(history, monkeypatch, tmp_path):
    """Run the real CLI/controller against a bare Git remote and fake GitHub APIs."""
    import os
    import shutil

    state = tmp_path / '.fixture'
    state.mkdir()
    scripts = tmp_path / 'core' / 'scripts'
    scripts.mkdir()
    shutil.copy(MODULE, scripts / 'release_automation.py')
    shutil.copy(MODULE.with_name('create-release.sh'), scripts / 'create-release.sh')
    installer = tmp_path / 'core/tests/skills/solar-client/test_install_solar_client.sh'
    installer.parent.mkdir(parents=True)
    installer.write_text('#!/usr/bin/env bash\n[[ "${FIXTURE_INSTALL_FAIL:-0}" != 1 ]]\n')
    with open('.git/info/exclude', 'a') as out:
        out.write('\n/.fixture/\n/core/scripts/\n/core/tests/\n')
    remote = state / 'origin.git'
    a.git('init', '--bare', '-q', str(remote))
    a.git('remote', 'set-url', 'origin', str(remote))
    a.git('push', '-q', 'origin', 'main')
    bins = state / 'bin'
    bins.mkdir()
    real_git = shutil.which('git')
    (bins / 'git').write_text('''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args[-3:] == ['remote', 'get-url', 'origin']:
    print('https://github.com/Example/Solar.git')
else:
    os.execv(os.environ['FIXTURE_REAL_GIT'], ['git', *args])
''')
    (bins / 'gh').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state = pathlib.Path(os.environ['FIXTURE_STATE'])
if args[:2] == ['auth', 'status']:
    sys.exit(0)
if args and args[0] == 'api' and '/check-runs' in args[1]:
    print(json.dumps({'check_runs': [{'name': f'Suite ({platform}-latest)', 'conclusion': 'success', 'status': 'completed'} for platform in ['ubuntu', 'macos']]}))
    sys.exit(0)
if args[:2] == ['release', 'view']:
    if not (state / 'release.json').exists():
        sys.exit(1)
    value = json.loads((state / 'release.json').read_text())
    print(json.dumps({'tagName': value['tag_name'], 'isDraft': False, 'isPrerelease': False}))
    sys.exit(0)
if args[:2] == ['release', 'create']:
    if (state / 'release.json').exists():
        sys.exit(2)
    notes = pathlib.Path(args[args.index('--notes-file') + 1]).read_text()
    (state / 'release.json').write_text(json.dumps({'tag_name': args[2], 'draft': False, 'prerelease': False, 'notes': notes}))
    sys.exit(0)
sys.exit(3)
''')
    (bins / 'curl').write_text('''#!/usr/bin/env python3
import os, pathlib, sys
if '%{http_code}' in sys.argv:
    print('200', end='')
else:
    print((pathlib.Path(os.environ['FIXTURE_STATE']) / 'release.json').read_text())
''')
    for executable in bins.iterdir():
        executable.chmod(0o755)
    event = state / 'event.json'
    event.write_text(json.dumps(history['event']))
    monkeypatch.setenv('PATH', str(bins) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('FIXTURE_REAL_GIT', real_git)
    monkeypatch.setenv('FIXTURE_STATE', str(state))
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('GITHUB_SHA', history['sha'])
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event))
    monkeypatch.setattr(a.sys, 'argv', ['release_automation.py', 'publish'])
    monkeypatch.setenv('FIXTURE_INSTALL_FAIL', '1')
    with pytest.raises(subprocess.CalledProcessError):
        a.main()
    assert not a.git('--git-dir', str(remote), 'tag', '--list')
    assert not (state / 'release.json').exists()
    monkeypatch.setenv('FIXTURE_INSTALL_FAIL', '0')
    a.main()
    assert a.git('--git-dir', str(remote), 'rev-parse', f'refs/tags/{VERSION}') == history['sha']
    assert json.loads((state / 'release.json').read_text())['tag_name'] == VERSION
    a.main()  # Same tag and Release: idempotent, no duplicate create.


def test_resuming_omitted_request_never_pushes_or_opens_pr(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    monkeypatch.setattr(a, 'live_registry', Mock(return_value={
        'schema': 1, 'paused': False, 'entries': [omission_entry(history)]}))
    a.pages.reset_mock()
    with pytest.raises(ValueError, match='cannot be resubmitted'):
        a.submit(REPO, VERSION)
    a.pages.assert_not_called()


@pytest.mark.parametrize('strict', [False, None])
def test_loose_or_missing_up_to_date_protection_refuses_submission(history, monkeypatch, strict):
    monkeypatch.setattr(a, 'api', Mock(side_effect=[
        {'allow_auto_merge': True, 'allow_merge_commit': True},
        {'contexts': list(a.CHECKS), 'strict': strict}]))
    with pytest.raises(ValueError, match='Require branches to be up to date'):
        a.repository_ready(REPO)


def test_strict_protection_with_both_suites_is_supported(history, monkeypatch):
    monkeypatch.setattr(a, 'api', Mock(side_effect=[
        {'allow_auto_merge': True, 'allow_merge_commit': True},
        {'contexts': list(a.CHECKS), 'strict': True}]))
    a.repository_ready(REPO)


def test_deleted_fork_cannot_crash_matching_release_submission(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    dead = {**history['pr'], 'head': {**history['pr']['head'], 'repo': None}}
    monkeypatch.setattr(a, 'pages', lambda path: [dead])
    original = a.run
    writes = []
    def run(*args):
        if args[0] == 'gh' or (args[0] == 'git' and args[1] == 'push'):
            writes.append(args)
            return 'fixture-pr'
        return original(*args)
    monkeypatch.setattr(a, 'run', run)
    a.submit(REPO, VERSION)
    assert any(cmd[:3] == ('gh', 'pr', 'create') for cmd in writes)


def test_resume_preview_binds_identity_and_changed_head_refuses(history, capsys, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    a.preview_resume(REPO, VERSION, history['head'])
    text = capsys.readouterr().out
    for expected in [VERSION, history['base'], history['head'], REPO, 'Effects:']:
        assert expected in text
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    a.git('commit', '--allow-empty', '-qm', 'concurrent change after preview')
    with pytest.raises(ValueError, match='changed after confirmation'):
        a.submit(REPO, VERSION, history['head'])


def test_integrated_drift_can_be_omitted_then_corrected_without_publishing(history, monkeypatch):
    # Simulate an old loose-protection merge, before strict readiness was enforced.
    a.git('reset', '--hard', history['base'])
    Path('parallel-fix.py').write_text('parallel_change = True\n')
    a.git('add', 'parallel-fix.py')
    a.git('commit', '-qm', 'another PR advances main while release CI runs')
    a.git('merge', '--no-ff', '-qm', 'old loose merge with drift', f'release/{VERSION}')
    drifted = a.git('rev-parse', 'HEAD')
    history['pr']['merge_commit_sha'] = drifted
    history['sha'] = drifted
    event = {**history['event'], 'after': drifted}
    with pytest.raises(ValueError, match='only release metadata'):
        a.validate_event(REPO, event, publish=True)
    with pytest.raises(ValueError, match='only release metadata'):
        a.guard_publication(REPO, VERSION, drifted)

    frozen = {'schema': 1, 'paused': True, 'entries': []}
    Path(a.OMISSIONS).write_text(json.dumps(frozen))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'protected recovery: freeze')
    freeze_sha = a.git('rev-parse', 'HEAD')
    data = {**frozen, 'entries': [omission_entry(history)]}
    Path(a.OMISSIONS).write_text(json.dumps(data))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'protected recovery: reconciled omission')
    monkeypatch.setattr(a, 'request_runs', Mock(return_value=[{'id': 55, 'status': 'completed'}]))
    monkeypatch.setattr(a, 'object_pages', Mock(return_value=[{'status': 'completed'}]))
    monkeypatch.setattr(a, 'api', Mock(return_value=None))
    a.validate_registry_change(REPO, freeze_sha, 'HEAD')

    data['paused'] = False
    Path(a.OMISSIONS).write_text(json.dumps(data))
    a.git('add', a.OMISSIONS)
    a.git('commit', '-qm', 'protected recovery: unfreeze after omission')
    monkeypatch.setattr(a, 'live_registry', Mock(return_value=data))
    a.require_published(REPO, history['intent'])
    with pytest.raises(ValueError, match='permanently omitted'):
        a.guard_publication(REPO, VERSION, drifted)

    # A new explicit request captures the corrected current main, not the old base.
    fresh_base = a.git('rev-parse', 'HEAD')
    new_intent = {'schema': 1, 'version': 'v1.2.0', 'base_sha': fresh_base}
    Path(a.INTENT).write_text(json.dumps(new_intent))
    Path(a.CLI).write_text('SOLAR_VERSION="1.2.0"\n')
    Path('CHANGELOG.md').write_text('## [1.2.0]\n- Corrected release\n')
    Path('README.md').write_text(f'<!-- solar-bootstrap-pin -->\nhttps://raw.githubusercontent.com/{REPO}/v1.2.0/core/skills/solar-client/scripts/bootstrap_solar_client.sh\n<!-- /solar-bootstrap-pin -->')
    a.git('add', '.')
    a.git('commit', '-qm', 'request higher corrected version after recovery')
    assert a.check_metadata('HEAD', new_intent) == 'v1.2.0'
    successor = a.git('rev-parse', 'HEAD')
    new_pr = {**history['pr'], 'merge_commit_sha': successor,
              'base': {'ref': 'main', 'sha': fresh_base},
              'head': {'ref': 'release/v1.2.0', 'sha': successor, 'repo': {'full_name': REPO}}}
    monkeypatch.setattr(a, 'pages', lambda path: [{'filename': name} for name in a.ALLOWED] if path.endswith('/files') else [new_pr])
    new_event = {**event, 'after': successor}
    assert a.validate_event(REPO, new_event, publish=True) == 'v1.2.0'
    a.git('update-ref', 'refs/remotes/origin/main', successor)
    a.guard_publication(REPO, 'v1.2.0', successor)
    assert not a.git('tag', '--list')  # Neither the defective version nor a replacement was published by recovery.


def test_command_failure_preserves_git_or_github_stderr(capsys):
    failure = subprocess.CalledProcessError(1, ['git', 'push'], stderr='remote: permission denied by repository policy')
    a.report_failure(failure)
    assert 'permission denied by repository policy' in capsys.readouterr().err


def test_submission_pushes_confirmed_sha_even_if_head_moves_during_queries(history, monkeypatch):
    a.git('checkout', f'release/{VERSION}')
    monkeypatch.setattr(a, 'repository_ready', lambda repo: None)
    def advance_head(repo):
        a.git('commit', '--allow-empty', '-qm', 'another process changes HEAD after validation')
        return {'schema': 1, 'paused': False, 'entries': []}
    monkeypatch.setattr(a, 'live_registry', advance_head)
    monkeypatch.setattr(a, 'pages', lambda path: [history['pr']])
    original = a.run
    writes = []
    def run(*args):
        if args[0] == 'gh' or (args[0] == 'git' and args[1] == 'push'):
            writes.append(args)
            return ''
        return original(*args)
    monkeypatch.setattr(a, 'run', run)
    a.submit(REPO, VERSION, history['head'])
    assert a.git('rev-parse', 'HEAD') != history['head']
    push = next(cmd for cmd in writes if cmd[:2] == ('git', 'push'))
    assert push[-1] == f'{history["head"]}:refs/heads/release/{VERSION}'
    assert not any('HEAD:' in arg for arg in push)
