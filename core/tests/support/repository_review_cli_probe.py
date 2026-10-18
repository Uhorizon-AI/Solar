#!/usr/bin/env python3
"""Opt-in, inference-free sandbox/constructor proofs for repository reviewers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def extra_cli_probe(provider):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills/solar-router/scripts'))
    from repository_cli_guards import prepare, write_json
    binary = shutil.which(provider)
    if not binary:
        raise SystemExit(provider + ' CLI is required')
    with tempfile.TemporaryDirectory(prefix='solar-repository-cli-') as name:
        top = Path(name)
        origin = top / 'synthetic-user'
        # Synthetic tokens only; help never sends a prompt or authenticates.
        auth = origin / ('.cursor' if sys.platform == 'darwin' else '.config/cursor')
        write_json(auth / 'auth.json', dict(accessToken='synthetic', refreshToken='synthetic'))
        token = origin / '.gemini/jetski-standalone-oauth-token'
        token.parent.mkdir(parents=True, exist_ok=True); token.write_text('synthetic')
        private = top / 'isolated'; private.mkdir(); cwd = private / 'repository'; cwd.mkdir()
        (cwd / 'source.md').write_text('unchanged')
        prepare(provider, binary, dict(HOME=str(origin), PATH=os.environ.get('PATH', '')), private, cwd,
                dict(system_prompt='Review.', user_prompt='Synthetic fixture.', model='unused-help-only'))
    assert not top.exists()
    print(json.dumps(dict(provider=provider, status='passed', inference_calls=0,
                         cli_help_checked=True, os_write_guard_checked=True,
                         model_behavior_verified=False, temporary_resources_cleaned=True)))


def main():
    if os.environ.get('SOLAR_TEST_REPOSITORY_CLI') != '1' or sys.platform not in {'darwin', 'linux'}:
        print(json.dumps(dict(status='skipped', reason='opt-in on macOS/Linux only')))
        return 0
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['codex', 'agent', 'agy', 'all'], default='codex')
    selected = parser.parse_args().provider
    if selected in {'agent', 'agy'}:
        extra_cli_probe(selected)
        return 0
    binary = shutil.which('codex')
    if not binary:
        raise SystemExit('codex CLI is required')
    with tempfile.TemporaryDirectory(prefix='solar-repository-sandbox-', dir='/private/tmp' if sys.platform == 'darwin' else None) as name:
        folder = Path(name)
        repo = folder / 'repository'; repo.mkdir()
        (repo / 'source.txt').write_text('original')
        home = folder / 'codex-home'; home.mkdir(mode=0o700)
        outside = folder / 'outside.txt'; outside.write_text('outside')
        # No account, credentials, providers or network calls. The child only
        # tries to change disposable files, including one outside its cwd.
        code = '''import json,sys
from pathlib import Path
root=Path(sys.argv[1]); outside=Path(sys.argv[2]); allowed=[]
assert (root/'source.txt').read_text()=='original'
for target in [root/'source.txt',root/'created.txt',outside]:
 try: target.write_text('bad');allowed.append(str(target))
 except OSError: pass
print(json.dumps(dict(read=True,write_successes=allowed)))
raise SystemExit(bool(allowed))
'''
        env = {k:v for k,v in os.environ.items() if k in {'HOME','PATH','USER','LANG','SYSTEMROOT'}}
        env['CODEX_HOME'] = str(home)
        args = [binary, 'sandbox', '--permission-profile', ':read-only', '-c', 'sandbox_mode="read-only"', '-c', 'approval_policy="never"',
                '-C', str(repo), '--', sys.executable, '-c', code, str(repo), str(outside)]
        done = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
        if done.returncode:
            print(done.stderr, file=sys.stderr)
            raise SystemExit('Sandbox unavailable or write protection failed: ' + done.stdout)
        result = json.loads(done.stdout)
        assert result == dict(read=True, write_successes=[]), result
        assert (repo/'source.txt').read_text()=='original' and outside.read_text()=='outside'
        print(json.dumps(dict(status='passed', inference_calls=0, source_unchanged=True,
                              outside_unchanged=True, temporary_resources_cleaned_on_exit=True)))
    if selected == 'all':
        for provider in ['agent', 'agy']:
            extra_cli_probe(provider)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
