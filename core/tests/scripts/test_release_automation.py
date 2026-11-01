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
    publish.assert_called_once_with(['bash', 'core/scripts/create-release.sh', '--publish', '--version', VERSION], check=True)


def test_pr_rebase_keeps_publisher_on_new_integrated_sha(history):
    a.git('reset', '--hard', history['base'])
    a.git('commit', '--allow-empty', '-qm', 'ordinary newer main')
    parent = a.git('rev-parse', 'HEAD')
    a.git('cherry-pick', history['head'])
    sha = a.git('rev-parse', 'HEAD')
    history['pr']['merge_commit_sha'] = sha
    assert a.git('rev-parse', f'{sha}^') == parent
    assert a.validate_event(REPO, {**history['event'], 'after': sha}, publish=True) == VERSION


def test_main_code_advance_before_merge_does_not_change_request(history):
    a.git('reset', '--hard', history['base'])
    Path('ordinary.py').write_text('unrelated = True\n')
    a.git('add', 'ordinary.py')
    a.git('commit', '-qm', 'ordinary code on main')
    a.git('merge', '--no-ff', '-qm', 'merge release', f'release/{VERSION}')
    sha = a.git('rev-parse', 'HEAD')
    history['pr']['merge_commit_sha'] = sha
    assert a.validate_event(REPO, {**history['event'], 'after': sha}, publish=True) == VERSION


def test_workflow_gates_and_permissions():
    workflow = MODULE.parents[2] / '.github' / 'workflows' / 'test-suite.yml'
    text = workflow.read_text()
    suites, publisher = text.split('\n  publish:', 1)
    assert 'contents: write' not in suites
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


@pytest.fixture
def candidate(history, monkeypatch):
    a.git('checkout', '-b', f'candidate/{VERSION}/{history["base"][:12]}', history['head'])
    a.git('branch', '-f', 'main', history['base'])
    a.git('branch', '-D', f'release/{VERSION}')
    intent = {**history['intent'], 'schema': 2, 'stage': 'candidate'}
    Path(a.INTENT).write_text(json.dumps(intent))
    a.git('add', a.INTENT)
    a.git('commit', '-qm', 'candidate metadata')
    history['candidate'] = a.git('rev-parse', 'HEAD')
    history['intent'] = intent
    a.git('update-ref', 'refs/remotes/origin/main', history['base'])
    monkeypatch.setattr(a, 'repository_ready', Mock())
    monkeypatch.setattr(a, 'pages', Mock(return_value=[]))
    calls = []
    real_run = a.run
    def run(*args):
        if args[0] == 'gh' or (args[0] == 'git' and args[1] in {'push', 'fetch'}):
            calls.append(args)
            return ''
        return real_run(*args)
    monkeypatch.setattr(a, 'run', run)
    history['calls'] = calls
    return history


def test_candidate_never_authorizes_publication(candidate):
    with pytest.raises(ValueError, match='not authorized'):
        a.check_metadata('HEAD', candidate['intent'])
    assert a.check_metadata('HEAD', candidate['intent'], allow_candidate=True) == VERSION


def test_upload_candidate_creates_no_pr_or_tag(candidate, capsys):
    a.upload_candidate(REPO, VERSION)
    a.repository_ready.assert_called_once_with(REPO, automatic=False)
    assert len(candidate['calls']) == 1
    assert candidate['calls'][0][:3] == ('git', 'push', '--no-follow-tags')
    assert not a.git('tag', '--list')
    output = capsys.readouterr().out
    assert f'solar client update --ref {candidate["candidate"]}' in output
    assert '--promote --tested-sha' in output


def test_promote_records_tested_sha_and_changes_only_intent(candidate, monkeypatch):
    submit = Mock()
    monkeypatch.setattr(a, 'submit', submit)
    a.promote(REPO, candidate['candidate'])
    intent = a.intent_at('HEAD')
    assert intent['stage'] == 'release' and intent['tested_sha'] == candidate['candidate']
    assert a.git('branch', '--show-current') == f'release/{VERSION}'
    assert a.git('diff', '--name-only', candidate['candidate'], 'HEAD') == a.INTENT
    assert a.check_metadata('HEAD', intent) == VERSION
    submit.assert_called_once_with(REPO, VERSION)


def test_promote_wrong_sha_does_not_modify_candidate(candidate):
    with pytest.raises(ValueError, match='exact locally tested'):
        a.promote(REPO, '0' * 40)
    assert a.git('rev-parse', 'HEAD') == candidate['candidate']
    assert a.intent_at('HEAD')['stage'] == 'candidate'


def test_promote_advanced_main_requires_retest(candidate):
    a.git('update-ref', 'refs/remotes/origin/main', candidate['sha'])
    with pytest.raises(ValueError, match='Main advanced'):
        a.promote(REPO, candidate['candidate'])
    assert a.git('rev-parse', 'HEAD') == candidate['candidate']


def test_promote_does_not_mix_another_version(candidate):
    with pytest.raises(ValueError, match='differs from the tested'):
        a.promote(REPO, candidate['candidate'], 'v9.9.9')


def test_promote_dirty_candidate_refused(candidate):
    Path('local-change').write_text('must be tested first')
    with pytest.raises(ValueError, match='must be clean'):
        a.promote(REPO, candidate['candidate'])


def test_post_test_changes_cannot_publish(candidate, monkeypatch):
    monkeypatch.setattr(a, 'submit', Mock())
    a.promote(REPO, candidate['candidate'])
    Path('another-fix.py').write_text('changed = True')
    a.git('add', 'another-fix.py')
    a.git('commit', '-qm', 'untested change')
    with pytest.raises(ValueError, match='differs from the locally tested'):
        a.check_metadata('HEAD', a.intent_at('HEAD'))


def test_candidate_pr_cannot_enter_release_pipeline(candidate):
    event = {'pull_request': {**candidate['pr'], 'head': {
        'ref': a.git('branch', '--show-current'), 'sha': candidate['candidate'], 'repo': {'full_name': REPO}}}}
    with pytest.raises(ValueError, match='not authorized'):
        a.validate_event(REPO, event)


def test_candidate_upload_does_not_need_automerge(history, monkeypatch):
    monkeypatch.setattr(a, 'api', Mock(return_value={'allow_auto_merge': False, 'allow_merge_commit': False}))
    a.repository_ready(REPO, automatic=False)
    assert a.api.call_count == 1


def test_candidate_preflight_allows_parallel_release(history, monkeypatch):
    a.git('checkout', 'main')
    a.git('reset', '--hard', history['base'])
    a.git('update-ref', 'refs/remotes/origin/main', history['base'])
    ready = Mock()
    monkeypatch.setattr(a, 'repository_ready', ready)
    real_git = a.git
    monkeypatch.setattr(a, 'git', lambda *args: '' if args[0] == 'fetch' else real_git(*args))
    a.check_prepare(REPO, candidate=True)
    ready.assert_called_once_with(REPO, automatic=False)
    a.pages.assert_not_called()
    a.api.assert_not_called()
