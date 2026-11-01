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


def check_metadata(sha, intent, diff_base=None, allow_candidate=False):
    common = {'schema', 'version', 'base_sha'}
    if not isinstance(intent, dict):
        raise ValueError('Invalid release intent schema')
    if intent.get('schema') == 1:
        valid = set(intent) == common
    else:
        valid = (intent.get('schema') == 2 and intent.get('stage') in {'candidate', 'release'}
                 and (set(intent) == common | {'stage'} or (intent.get('stage') == 'release' and set(intent) == common | {'stage', 'tested_sha'})))
    if not valid:
        raise ValueError('Invalid release intent schema')
    if intent.get('stage') == 'candidate' and not allow_candidate:
        raise ValueError('Candidate is not authorized for publication; explicitly promote its tested SHA')
    tested = intent.get('tested_sha')
    if 'tested_sha' in intent:
        if not isinstance(tested, str) or not re.fullmatch(r'[0-9a-f]{40}', tested):
            raise ValueError('Invalid tested candidate SHA')
        git('merge-base', '--is-ancestor', tested, sha)
        if set(git('diff', '--name-only', tested, sha).splitlines()) - {INTENT}:
            raise ValueError('Code differs from the locally tested candidate; prepare and test a fresh candidate')
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


def repository_ready(repo, automatic=True):
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        raise ValueError('Submit from the maintainer CLI, not an Actions token/event chain')
    require_remote(repo)
    info = api(f'repos/{repo}')
    if not automatic:
        return
    if not info.get('allow_auto_merge') or not info.get('allow_merge_commit'):
        raise ValueError('Enable Allow auto-merge and merge commits in repository Settings before starting. No settings were changed.')
    protection = api(f'repos/{repo}/branches/main/protection/required_status_checks')
    contexts = set(protection.get('contexts', [])) | {r['context'] for r in protection.get('checks', [])}
    if not CHECKS <= contexts:
        raise ValueError('Both Test suite checks must be required on main')


def check_prepare(repo, candidate=False):
    if candidate:
        repository_ready(repo, automatic=False)
    else:
        repository_ready(repo)
    git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
    if git('rev-parse', 'HEAD') != git('rev-parse', 'origin/main'):
        raise ValueError('Start from main synchronized with origin/main')
    if git('status', '--porcelain'):
        raise ValueError('Working tree must be clean')
    if candidate:
        return  # An experiment does not authorize or serialize stable publication.
    if any(p['head']['ref'].startswith('release/') for p in pages(f'repos/{repo}/pulls?state=open&base=main')):
        raise ValueError('A release PR is already open; resume it rather than creating another')
    require_published(repo, intent_at('origin/main'))


def submit(repo, version):
    repository_ready(repo)
    sha = git('rev-parse', 'HEAD')
    intent = intent_at(sha)
    if not intent or check_metadata(sha, intent) != version or git('branch', '--show-current') != f'release/{version}':
        raise ValueError('Release branch does not match its committed intent')
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


def upload_candidate(repo, version):
    repository_ready(repo, automatic=False)
    sha = git('rev-parse', 'HEAD')
    intent = intent_at(sha)
    if not intent or intent.get('stage') != 'candidate' or check_metadata(sha, intent, allow_candidate=True) != version:
        raise ValueError('Not a prepared candidate')
    branch = git('branch', '--show-current')
    if branch != f'candidate/{version}/{intent["base_sha"][:12]}' or git('status', '--porcelain'):
        raise ValueError('Upload requires the clean prepared candidate branch')
    run('git', 'push', '--no-follow-tags', '-u', 'origin', f'HEAD:refs/heads/{branch}')
    print(f'Candidate uploaded: {sha}\nTest locally: solar client update --ref {sha}\n'
          f'No PR, auto-merge, tag or stable Release requested.\n'
          f'After validation: bash core/scripts/create-release.sh --promote --tested-sha {sha}')


def promote(repo, tested, version=None):
    repository_ready(repo)
    sha = git('rev-parse', 'HEAD')
    intent = intent_at(sha)
    if not tested or tested != sha:
        raise ValueError('Check out the exact locally tested candidate and pass its full SHA with --tested-sha')
    if not intent or intent.get('stage') != 'candidate':
        raise ValueError('Promotion requires a candidate, not an existing release request')
    requested = check_metadata(sha, intent, allow_candidate=True)
    if version and version != requested:
        raise ValueError('Requested version differs from the tested candidate')
    if git('status', '--porcelain'):
        raise ValueError('Candidate working tree must be clean')
    git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
    if git('rev-parse', 'origin/main') != intent['base_sha']:
        raise ValueError('Main advanced since this candidate; prepare and test a fresh candidate from current main')
    if any(p['head']['ref'].startswith('release/') for p in pages(f'repos/{repo}/pulls?state=open&base=main')):
        raise ValueError('A release request is already open; stop or finish it before promotion')
    require_published(repo, intent_at('origin/main'))
    git('switch', '-c', f'release/{requested}')
    intent.update(stage='release', tested_sha=tested)
    Path(INTENT).write_text(json.dumps(intent, indent=2) + '\n')
    git('add', INTENT)
    git('commit', '-m', f'chore(release): promote tested {requested}')
    submit(repo, requested)


def validate_event(repo, event, publish=False):
    sha = git('rev-parse', 'HEAD')
    if publish:
        if event.get('ref') != 'refs/heads/main' or event.get('after') != sha or event.get('repository', {}).get('full_name') != repo:
            raise ValueError('Publisher requires the exact main push SHA in this repository')
        parent = git('rev-parse', f'{sha}^1')
    else:
        parent = event.get('pull_request', {}).get('base', {}).get('sha') or git('rev-parse', f'{sha}^1')
    intent = intent_at(sha)
    before = intent_at(parent)
    if intent == before:
        return None  # Ordinary PR/main commit; inherited intent never republishes.
    if not intent:
        raise ValueError('Release intent cannot be removed')
    version = check_metadata(sha, intent, diff_base=parent)
    if before and version_tuple(version) <= version_tuple(before['version']):
        raise ValueError('Release request is stale: version does not exceed its predecessor')
    require_published(repo, before)
    if publish:
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
    else:
        pr = event.get('pull_request')
        if pr and (pr['head']['ref'] != f'release/{version}' or not pr['head']['repo'] or pr['head']['repo']['full_name'] != repo):
            raise ValueError('Release intent must come from the matching same-repository release branch')
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check', 'check-candidate', 'check-version', 'write-intent', 'candidate', 'promote', 'resume', 'submit', 'validate', 'publish'])
    parser.add_argument('--version')
    parser.add_argument('--stage', choices=['candidate', 'release'], default='release')
    parser.add_argument('--tested-sha')
    args = parser.parse_args()
    repo = os.environ.get('SOLAR_RELEASE_REPO', 'Uhorizon-AI/Solar')
    if args.mode == 'check':
        check_prepare(repo)
    elif args.mode == 'check-candidate':
        check_prepare(repo, candidate=True)
    elif args.mode == 'check-version':
        version_tuple(args.version)
        if api(f'repos/{repo}/git/ref/tags/{args.version}', missing=True):
            raise ValueError('Requested version already has a remote tag; use recovery instead')
        latest = api(f'repos/{repo}/releases/latest', missing=True)
        if latest and version_tuple(args.version) <= version_tuple(latest['tag_name']):
            raise ValueError('Requested version must exceed the latest stable release')
    elif args.mode == 'write-intent':
        version_tuple(args.version)
        base = git('rev-parse', 'HEAD')
        path = Path(INTENT)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'schema': 2, 'version': args.version, 'base_sha': base, 'stage': args.stage}, indent=2) + '\n')
    elif args.mode == 'candidate':
        upload_candidate(repo, args.version)
    elif args.mode == 'promote':
        promote(repo, args.tested_sha, args.version)
    elif args.mode == 'resume':
        intent = intent_at('HEAD')
        if not intent or (args.version and args.version != intent['version']):
            raise ValueError('Resume requires the matching committed request')
        if intent.get('stage') == 'candidate':
            upload_candidate(repo, intent['version'])
        else:
            submit(repo, intent['version'])
    elif args.mode == 'submit':
        submit(repo, args.version)
    else:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        version = validate_event(repo, event, publish=args.mode == 'publish')
        if version and args.mode == 'publish':
            # Existing manual path enforces exact checks, integration and tag identity,
            # runs installer acceptance and creates/verifies the GitHub Release.
            subprocess.run(['bash', 'core/scripts/create-release.sh', '--publish', '--version', version], check=True)
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
