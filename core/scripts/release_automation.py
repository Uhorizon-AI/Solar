#!/usr/bin/env python3
"""Bound release requests to committed metadata and GitHub's protected PR flow."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

INTENT = '.github/solar-release.json'
OMISSIONS = '.github/solar-release-omissions.json'
CLI = 'core/skills/solar-client/scripts/solar'
ALLOWED = {INTENT, CLI, 'CHANGELOG.md', 'README.md'}
CHECKS = {'Suite (ubuntu-latest)', 'Suite (macos-latest)'}


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout.strip()


def api(path, missing=False):
    result = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    if result.returncode:
        if missing and '(HTTP 404)' in result.stderr:
            return None
        raise ValueError(f'GitHub request failed: {path}: {result.stderr.strip()}')
    return json.loads(result.stdout)


def pages(path):
    rows = []
    for page in range(1, 101):
        data = api(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
        rows.extend(data)
        if len(data) < 100:
            return rows
    raise ValueError('GitHub pagination limit reached; refusing incomplete evidence')


def git(*args):
    return run('git', *args)


def text_at(sha, path):
    return git('show', f'{sha}:{path}')


def intent_at(sha):
    paths = git('ls-tree', '--name-only', sha, '--', INTENT)
    return json.loads(text_at(sha, INTENT)) if paths else None


def version_tuple(version):
    if not re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version):
        raise ValueError(f'Invalid release version: {version}')
    return tuple(map(int, version[1:].split('.')))


def check_metadata(sha, intent, diff_base=None):
    if not isinstance(intent, dict) or set(intent) != {'schema', 'version', 'base_sha'} or intent['schema'] != 1:
        raise ValueError('Invalid release intent schema')
    version = intent['version']
    version_tuple(version)
    base = intent['base_sha']
    if not isinstance(base, str) or not re.fullmatch(r'[0-9a-f]{40}', base):
        raise ValueError('Invalid release base SHA')
    git('merge-base', '--is-ancestor', base, sha)
    changed = set(git('diff', '--name-only', diff_base or base, sha).splitlines())
    if not changed <= ALLOWED or INTENT not in changed:
        raise ValueError('Release request must change only release metadata')
    before_cli = text_at(diff_base or base, CLI)
    after_cli = text_at(sha, CLI)
    previous_version = re.search(r'^SOLAR_VERSION="([^"]+)"$', before_cli, re.M)
    cli_version = re.search(r'^SOLAR_VERSION="([^"]+)"$', after_cli, re.M)
    normalize = lambda text: re.sub(r'^SOLAR_VERSION="[^"]+"$', 'SOLAR_VERSION="VERSION"', text, flags=re.M)
    if normalize(before_cli) != normalize(after_cli):
        raise ValueError('Release PR may change only the CLI version, not its code')
    if not previous_version or not cli_version or cli_version[1] != version[1:]:
        raise ValueError('Release intent and CLI version differ')
    if version_tuple(version) <= version_tuple('v' + previous_version[1]):
        raise ValueError('Release version must increase')
    if not re.search(rf'^## \[{re.escape(version[1:])}\]', text_at(sha, 'CHANGELOG.md'), re.M):
        raise ValueError('Release changelog section is missing')
    repo = os.environ.get('SOLAR_RELEASE_REPO', 'Uhorizon-AI/Solar')
    pin = f'https://raw.githubusercontent.com/{repo}/{version}/core/skills/solar-client/scripts/bootstrap_solar_client.sh'
    readme = text_at(sha, 'README.md')
    block = re.search(r'<!-- solar-bootstrap-pin -->(.*?)<!-- /solar-bootstrap-pin -->', readme, re.S)
    if not block or pin not in block[1]:
        raise ValueError('README bootstrap pin and release intent differ')
    normalize_readme = lambda text: re.sub(r'<!-- solar-bootstrap-pin -->.*?<!-- /solar-bootstrap-pin -->', 'BOOTSTRAP', text, flags=re.S)
    if normalize_readme(text_at(diff_base or base, 'README.md')) != normalize_readme(readme):
        raise ValueError('Release PR may change only the README bootstrap block')
    return version


def require_published(repo, intent):
    if not intent:
        return
    version = intent['version']
    registry = live_registry(repo)
    omitted = [e for e in registry['entries'] if e['version'] == version]
    if omitted:
        if intent_at(omitted[0]['request_sha']) != intent:
            raise ValueError('Omitted predecessor identity conflicts with its intent')
        return
    release = api(f'repos/{repo}/releases/tags/{version}', missing=True)
    if not release or release.get('draft') or release.get('prerelease') or release.get('tag_name') != version:
        raise ValueError(f'Previous release {version} is not published; recover it before requesting another')
    ref = api(f'repos/{repo}/git/ref/tags/{version}')['object']
    if ref['type'] == 'tag':
        ref = api(f'repos/{repo}/git/tags/{ref["sha"]}')['object']
    if ref['type'] != 'commit':
        raise ValueError('Previous release tag is not a commit')
    pinned = intent_at(ref['sha'])
    if pinned != intent:
        raise ValueError('Previous release tag does not match its committed intent')


def require_remote(repo):
    origin = git('remote', 'get-url', 'origin')
    if origin not in {f'git@github.com:{repo}.git', f'https://github.com/{repo}.git', f'https://github.com/{repo}'}:
        raise ValueError(f'origin must point to {repo}')


def repository_ready(repo):
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        raise ValueError('Submit from the maintainer CLI, not an Actions token/event chain')
    require_remote(repo)
    info = api(f'repos/{repo}')
    if not info.get('allow_auto_merge') or not info.get('allow_merge_commit'):
        raise ValueError('Enable Allow auto-merge and merge commits in repository Settings before starting. No settings were changed.')
    protection = api(f'repos/{repo}/branches/main/protection/required_status_checks')
    contexts = set(protection.get('contexts', [])) | {r['context'] for r in protection.get('checks', [])}
    if not CHECKS <= contexts:
        raise ValueError('Both Test suite checks must be required on main')


def check_prepare(repo):
    repository_ready(repo)
    git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
    if git('rev-parse', 'HEAD') != git('rev-parse', 'origin/main'):
        raise ValueError('Start from main synchronized with origin/main')
    if git('status', '--porcelain'):
        raise ValueError('Working tree must be clean')
    if any(p['head']['ref'].startswith('release/') for p in pages(f'repos/{repo}/pulls?state=open&base=main')):
        raise ValueError('A release PR is already open; resume it rather than creating another')
    if live_registry(repo)['paused']:
        raise ValueError('Release admission is frozen for recovery')
    require_published(repo, intent_at('origin/main'))


def submit(repo, version):
    repository_ready(repo)
    sha = git('rev-parse', 'HEAD')
    intent = intent_at(sha)
    if not intent or check_metadata(sha, intent) != version or git('branch', '--show-current') != f'release/{version}':
        raise ValueError('Release branch does not match its committed intent')
    registry = live_registry(repo)
    if registry['paused']:
        raise ValueError('Release admission is frozen for recovery')
    if any(e['version'] == version or e['request_sha'] == sha for e in registry['entries']):
        raise ValueError('Omitted requests cannot be resubmitted')
    branch = f'release/{version}'
    # Reuse a PR if a prior submission stopped after creation. Do not duplicate it.
    existing = pages(f'repos/{repo}/pulls?state=open&base=main')
    others = [p for p in existing if p['head']['ref'].startswith('release/') and p['head']['ref'] != branch]
    if others:
        raise ValueError('Another release request is already open')
    matches = [p for p in existing if p['head']['ref'] == branch and p['head']['repo']['full_name'] == repo]
    if matches and matches[0]['head']['sha'] != sha:
        raise ValueError('Existing release PR has another head; inspect it before resuming')
    run('git', 'push', '--no-follow-tags', '-u', 'origin', f'HEAD:refs/heads/{branch}')
    if matches:
        pr = matches[0]
        url = pr['html_url']
    else:
        body = (f'Request publication of **{version}** after required checks and reviews.\n\n'
                f'Prepared head: `{sha}`; base: `{intent["base_sha"]}`.\n\n'
                'This PR requests native auto-merge without bypassing protections. After merge, '
                'the main workflow tests and publishes the exact integrated SHA. '
                'Merging is not proof of publication; follow the Test suite Actions run.\n\n'
                'If interrupted, resume with `create-release.sh --resume`.')
        with tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', suffix='.md') as notes:
            notes.write(body)
            notes.flush()
            url = run('gh', 'pr', 'create', '--repo', repo, '--base', 'main', '--head', branch,
                      '--title', f'chore(release): {version}', '--body-file', notes.name)
    # Native auto-merge keeps required checks/reviews authoritative; never --admin.
    run('gh', 'pr', 'merge', url, '--repo', repo, '--auto', '--merge', '--match-head-commit', sha)
    print(f'Release request submitted: {url}\nGitHub will integrate and publish after its gates pass. '
          'Follow the PR and the Test suite run; the terminal can be closed.')


def require_release_pr(repo, sha, intent):
    version = intent['version']
    prs = pages(f'repos/{repo}/commits/{sha}/pulls')
    matches = [p for p in prs if p.get('merged_at') and p.get('merge_commit_sha') == sha
               and p['base']['ref'] == 'main' and p['head']['ref'] == f'release/{version}'
               and p['head']['repo'] and p['head']['repo']['full_name'] == repo]
    if len(matches) != 1:
        raise ValueError('Release push has no unique matching merged release PR')
    pr = matches[0]
    files = {f['filename'] for f in pages(f'repos/{repo}/pulls/{pr["number"]}/files')}
    if not files <= ALLOWED or INTENT not in files:
        raise ValueError('Release PR contains non-metadata changes')
    # A merged PR branch may already have been deleted. Its persistent PR ref
    # still allows inspection of the exact request, without moving any branch.
    try:
        git('cat-file', '-e', pr['head']['sha'] + '^{commit}')
    except subprocess.CalledProcessError:
        git('fetch', '--no-tags', 'origin', f'refs/pull/{pr["number"]}/head')
        if git('rev-parse', 'FETCH_HEAD') != pr['head']['sha']:
            raise ValueError('Fetched release PR head differs from merged provenance')
    check_metadata(pr['head']['sha'], intent)
    if intent_at(pr['head']['sha']) != intent:
        raise ValueError('Merged intent differs from release PR head')


def validate_event(repo, event, publish=False):
    sha = git('rev-parse', 'HEAD')
    if publish:
        if event.get('ref') != 'refs/heads/main' or event.get('after') != sha or event.get('repository', {}).get('full_name') != repo:
            raise ValueError('Publisher requires the exact main push SHA in this repository')
        parent = git('rev-parse', f'{sha}^1')
    else:
        parent = event.get('pull_request', {}).get('base', {}).get('sha') or git('rev-parse', f'{sha}^1')
    validate_registry_change(repo, parent, sha)
    intent = intent_at(sha)
    before = intent_at(parent)
    if intent == before:
        return None  # Ordinary PR/main commit; inherited intent never republishes.
    if not intent:
        raise ValueError('Release intent cannot be removed')
    version = check_metadata(sha, intent)
    if before and version_tuple(version) <= version_tuple(before['version']):
        raise ValueError('Release request is stale: version does not exceed its predecessor')
    require_published(repo, before)
    if publish:
        require_release_pr(repo, sha, intent)
    else:
        pr = event.get('pull_request')
        if pr and (pr['head']['ref'] != f'release/{version}' or not pr['head']['repo'] or pr['head']['repo']['full_name'] != repo):
            raise ValueError('Release intent must come from the matching same-repository release branch')
    return version


def object_pages(path, key):
    rows = []
    for page in range(1, 101):
        values = api(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')[key]
        rows.extend(values)
        if len(values) < 100:
            return rows
    raise ValueError('Incomplete workflow evidence')


def registry_at(ref):
    if not git('ls-tree', '--name-only', ref, '--', OMISSIONS):
        return {'schema': 1, 'paused': False, 'entries': []}
    return check_registry(json.loads(text_at(ref, OMISSIONS)))


def check_registry(data):
    if (not isinstance(data, dict) or set(data) != {'schema', 'paused', 'entries'}
            or type(data['schema']) is not int or data['schema'] != 1
            or type(data['paused']) is not bool or not isinstance(data['entries'], list)):
        raise ValueError('Invalid omissions registry schema')
    versions, shas = set(), set()
    for entry in data['entries']:
        fields = {'version', 'request_sha', 'reason', 'runs', 'evidence'}
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ValueError('Invalid omission entry fields')
        version_tuple(entry['version'])
        if not isinstance(entry['request_sha'], str) or not re.fullmatch(r'[0-9a-f]{40}', entry['request_sha']):
            raise ValueError('Omission requires full integrated request SHA')
        if not isinstance(entry['reason'], str) or not entry['reason'].strip():
            raise ValueError('Omission requires a reason')
        evidence = entry['evidence']
        if (not isinstance(evidence, dict) or set(evidence) != {'writers_stopped', 'outcomes_reconciled', 'notes'}
                or evidence['writers_stopped'] is not True or evidence['outcomes_reconciled'] is not True
                or not isinstance(evidence['notes'], str) or not evidence['notes'].strip()):
            raise ValueError('Unresolved writers or remote outcomes block omission; explicit operator evidence is required')
        runs = entry['runs']
        if not isinstance(runs, list) or not runs or any(type(r) is not int or r <= 0 for r in runs) or len(set(runs)) != len(runs):
            raise ValueError('Omission requires unique positive run IDs')
        if entry['version'] in versions or entry['request_sha'] in shas:
            raise ValueError('Duplicate omission identity')
        versions.add(entry['version'])
        shas.add(entry['request_sha'])
    return data


def live_registry(repo):
    require_remote(repo)
    git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
    return registry_at('origin/main')


def request_runs(repo, sha):
    return [r for r in object_pages(f'repos/{repo}/actions/workflows/test-suite.yml/runs?event=push&head_sha={sha}', 'workflow_runs')
            if r['head_sha'] == sha and r['head_branch'] == 'main' and r['event'] == 'push']


def validate_registry_change(repo, parent, sha):
    before, after = registry_at(parent), registry_at(sha)
    if before == after:
        return
    count = len(before['entries'])
    if after['entries'][:count] != before['entries']:
        raise ValueError('Omissions are append-only; old records cannot change')
    added = after['entries'][count:]
    if not added:
        return  # Explicit protected recovery PR may pause/unpause admissions.
    if not before['paused'] or not after['paused']:
        raise ValueError('Freeze admission in a prior merged PR; do not unfreeze while recording omissions')
    # Existing registry protection is supplemented by live API evidence. Evidence
    # of completed jobs is NOT proof about an API write already accepted. The
    # operator must reconcile that uncertainty, or must not submit this recovery PR.
    for entry in added:
        intent = intent_at(entry['request_sha'])
        if not intent or check_metadata(entry['request_sha'], intent) != entry['version']:
            raise ValueError('Omission does not identify a valid integrated release request')
        git('merge-base', '--is-ancestor', entry['request_sha'], parent)
        require_release_pr(repo, entry['request_sha'], intent)
        runs = request_runs(repo, entry['request_sha'])
        if not runs or {r['id'] for r in runs} != set(entry['runs']):
            raise ValueError('Omission must enumerate every observed request run')
        for run in runs:
            if run['status'] != 'completed':
                raise ValueError('A request run is still active; omission is blocked')
            jobs = object_pages(f'repos/{repo}/actions/runs/{run["id"]}/jobs?filter=all', 'jobs')
            if not jobs or any(j['status'] != 'completed' for j in jobs):
                raise ValueError('A publisher job/attempt is unresolved; omission is blocked')
        release = api(f'repos/{repo}/releases/tags/{entry["version"]}', missing=True)
        if release and not release.get('draft'):
            raise ValueError('Release was published; do not classify it as omitted')
        ref = api(f'repos/{repo}/git/ref/tags/{entry["version"]}', missing=True)
        if ref:
            obj = ref['object']
            if obj['type'] == 'tag':
                obj = api(f'repos/{repo}/git/tags/{obj["sha"]}')['object']
            if obj['type'] != 'commit' or obj['sha'] != entry['request_sha']:
                raise ValueError('Partial tag identity conflicts; reconcile before omission')


def guard_publication(repo, version, sha):
    registry = live_registry(repo)
    if registry['paused']:
        raise ValueError('Publication is paused for recovery; no writes allowed')
    if any(e['version'] == version or e['request_sha'] == sha for e in registry['entries']):
        raise ValueError('Request is permanently omitted; old runs cannot publish it')
    intent = intent_at(sha)
    if not intent or check_metadata(sha, intent) != version:
        raise ValueError('Writer does not match an authorized release intent')
    git('merge-base', '--is-ancestor', sha, 'origin/main')


def retry_remote(repo, version=None):
    require_remote(repo)
    registry = live_registry(repo)
    if registry['paused']:
        raise ValueError('Recovery freeze blocks retries; reconcile before resuming')
    # Find the immutable integrated intent, never a new tip chosen at retry time.
    matching_requests = []
    for sha in git('log', '--first-parent', '--format=%H', 'origin/main', '--', INTENT).splitlines():
        intent = intent_at(sha)
        if not intent or (version and intent['version'] != version):
            continue
        if intent_at(git('rev-parse', f'{sha}^1')) != intent:
            matching_requests.append((sha, intent['version']))
    if not matching_requests:
        raise ValueError('No integrated automated request matches; legacy recovery needs an explicit separate decision')
    sha, selected = matching_requests[0]
    guard_publication(repo, selected, sha)
    runs = request_runs(repo, sha)
    if not runs:
        raise ValueError('No main CI run found for the exact request; inspect Actions')
    latest = max(runs, key=lambda r: r['id'])
    if latest['status'] != 'completed':
        raise ValueError('Request already has an active run; wait for its result')
    command = ['gh', 'run', 'rerun', str(latest['id']), '--repo', repo]
    if latest.get('conclusion') != 'success':
        command.append('--failed')
    run(*command)
    print(f'Retry submitted for {selected} at {sha}: run {latest["id"]}. No local publisher was started.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check', 'check-version', 'write-intent', 'submit', 'guard', 'retry', 'validate', 'publish'])
    parser.add_argument('--version')
    parser.add_argument('--sha')
    args = parser.parse_args()
    repo = os.environ.get('SOLAR_RELEASE_REPO', 'Uhorizon-AI/Solar')
    if args.mode == 'check':
        check_prepare(repo)
    elif args.mode == 'check-version':
        version_tuple(args.version)
        current = re.search(r'^SOLAR_VERSION="([^"]+)"$', text_at('HEAD', CLI), re.M)
        if not current or version_tuple(args.version) <= version_tuple('v' + current[1]):
            raise ValueError('Requested version must exceed the integrated CLI version, including omitted versions')
        registry = live_registry(repo)
        if any(version_tuple(args.version) <= version_tuple(e['version']) for e in registry['entries']):
            raise ValueError('Requested version must exceed allocated omitted versions')
        if api(f'repos/{repo}/git/ref/tags/{args.version}', missing=True):
            raise ValueError('Requested version already has a remote tag; use recovery instead')
        latest = api(f'repos/{repo}/releases/latest', missing=True)
        if latest and version_tuple(args.version) <= version_tuple(latest['tag_name']):
            raise ValueError('Requested version must exceed the latest stable release')
    elif args.mode == 'write-intent':
        version_tuple(args.version)
        base = git('rev-parse', 'HEAD')
        if args.sha and base != args.sha:
            raise ValueError('Release base changed since explicit authorization')
        path = Path(INTENT)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'schema': 1, 'version': args.version, 'base_sha': base}, indent=2) + '\n')
    elif args.mode == 'guard':
        guard_publication(repo, args.version, args.sha)
    elif args.mode == 'retry':
        retry_remote(repo, args.version)
    elif args.mode == 'submit':
        submit(repo, args.version)
    else:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        version = validate_event(repo, event, publish=args.mode == 'publish')
        if version and args.mode == 'publish':
            # Existing manual path enforces exact checks, integration and tag identity,
            # runs installer acceptance and creates/verifies the GitHub Release.
            guard_publication(repo, version, git('rev-parse', 'HEAD'))
            subprocess.run(['bash', 'core/scripts/create-release.sh', '--publish', '--version', version],
                           check=True, env={**os.environ, 'SOLAR_RELEASE_INTERNAL_PUBLISH': git('rev-parse', 'HEAD')})
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as out:
                out.write(f'### Release\n\n{version + ": publication verified" if version and args.mode == "publish" else "No release published by this step."}\n')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}\nNo release success is implied. Inspect the PR/Actions run. '
              'Resume submission with --resume; rerun failed jobs after correcting prerequisites. '
              'Do not move existing tags.', file=sys.stderr)
        sys.exit(1)
