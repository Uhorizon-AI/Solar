"""Cursor/Agy repository readers with private configuration and OS write guards.

No model calls in preflight. A supported help surface alone is not proof of model
quality or of provider-side context isolation. See repository-readonly-review.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


from cli_capabilities import discover, unsupported


def refused(reason='boundary_unavailable', stage='write_guard'):
    return unsupported('repository_reader', stage, reason)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def credential(source, target):
    """Copy only a bounded regular auth file, without following links."""
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536 or info.st_uid != os.getuid():
                raise refused('credentials_unavailable', 'credentials')
            raw = file.read(65537)
        if not raw or len(raw) > 65536:
            raise refused('credentials_unavailable', 'credentials')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(raw)
        target.chmod(0o600)
    except OSError:
        raise refused('credentials_unavailable', 'credentials') from None


def cursor_auth(origin, home):
    """Use subscription tokens only; never silently switch to API-key billing."""
    source = origin / ('.cursor' if sys.platform == 'darwin' else '.config/cursor') / 'auth.json'
    target = home / ('.cursor' if sys.platform == 'darwin' else '.config/cursor') / 'auth.json'
    if source.exists() or source.is_symlink():
        credential(source, target)
        try:
            auth = json.loads(target.read_text())
        except (ValueError, OSError):
            raise refused('credentials_unavailable', 'credentials') from None
    elif sys.platform == 'darwin':
        # Read selected entries only. The CLI receives a private file store and
        # cannot refresh or update the user's real keychain entries.
        auth = {}
        for field, service in [('accessToken', 'cursor-access-token'), ('refreshToken', 'cursor-refresh-token')]:
            try:
                done = subprocess.run(['/usr/bin/security', 'find-generic-password', '-a', 'cursor-user',
                                       '-s', service, '-w'], capture_output=True, text=True, timeout=10)
                if done.returncode or not done.stdout.strip():
                    raise refused('credentials_unavailable', 'credentials')
                auth[field] = done.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                raise refused('credentials_unavailable', 'credentials') from None
    else:
        raise refused('credentials_unavailable', 'credentials')
    if not all(isinstance(auth.get(k), str) and auth[k] for k in ('accessToken', 'refreshToken')):
        raise refused('credentials_unavailable', 'credentials')
    write_json(target, {k: auth[k] for k in ('accessToken', 'refreshToken')})


def guard_prefix(private, cwd):
    """Read-only host and snapshot; writes allowed only in disposable CLI state."""
    private, cwd = Path(private).resolve(), Path(cwd).resolve()
    if cwd.parent != private or private == Path('/'):
        raise refused()
    # HOME redirection is not enough if a CLI resolves its account's home via
    # the OS user database. Prevent reads of the real account's CLI/config trees
    # too. Binaries under .local/share remain readable.
    origin = Path.home().resolve()
    protected = [origin / name for name in ('.cursor', '.gemini', '.claude', '.codex', '.agy', '.config')]
    if any(private == path or path in private.parents for path in protected):
        raise refused()
    if sys.platform == 'darwin':
        binary = '/usr/bin/sandbox-exec'
        if not Path(binary).is_file():
            raise refused()
        # JSON quoting is also valid for SBPL string literals; never interpolate
        # an unquoted path into the policy language.
        profile = ('(version 1)(allow default)(deny file-write*)'
                   f'(allow file-write* (subpath {json.dumps(str(private))}) (literal "/dev/null"))'
                   f'(deny file-write* (subpath {json.dumps(str(cwd))}))'
                   + ''.join(f'(deny file-read* (subpath {json.dumps(str(path))}))' for path in protected))
        policy = private / 'write-guard.sb'
        policy.write_text(profile)
        return [binary, '-f', str(policy)]
    if sys.platform == 'linux':
        binary = shutil.which('bwrap', path='/usr/bin:/bin')
        if not binary:
            raise refused()
        hidden = []
        for path in protected:
            if path.is_symlink():
                raise refused()
            if path.is_dir():
                hidden += ['--tmpfs', str(path)]
        return [binary, '--die-with-parent', '--new-session', '--unshare-pid', '--ro-bind', '/', '/',
                '--bind', str(private), str(private), '--ro-bind', str(cwd), str(cwd),
                '--proc', '/proc', '--dev', '/dev', *hidden, '--chdir', str(cwd), '--']
    raise refused()


def probe_guard(prefix, env, private, cwd):
    """Exercise enforcement before any provider starts, not just config intent."""
    # One disposable sentinel outside the writable CLI state, owned by this
    # invocation. This tests host writes as well as snapshot writes.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='solar-review-outside-') as area:
        outside = Path(area).resolve() / 'sentinel'
        inside = cwd / '.solar-write-probe'
        # Probe an existing tracked file plus creation, so read-only mount and
        # overwrite behavior are both checked. No files in the source repo.
        existing = next(p for p in cwd.rglob('*') if p.is_file())
        original = existing.read_bytes()
        outside.write_text('unchanged')
        code = '''import os,pathlib,sys
existing,inside,outside,state=map(pathlib.Path,sys.argv[1:])
existing.read_bytes()
for path in (existing,inside,outside):
 try:
  path.write_bytes(b'FORBIDDEN')
 except OSError: pass
 else: sys.exit(12)
state.write_text('allowed')
'''
        state = private / 'state-probe'
        try:
            done = subprocess.run([*prefix, sys.executable, '-B', '-c', code, str(existing),
                                   str(inside), str(outside), str(state)], cwd=cwd, env=env,
                                  capture_output=True, timeout=15)
            if (done.returncode or existing.read_bytes() != original or inside.exists()
                    or outside.read_text() != 'unchanged' or state.read_text() != 'allowed'):
                raise refused('write_guard_probe_failed')
        except subprocess.TimeoutExpired:
            raise refused('write_guard_probe_timeout') from None
        except (OSError, subprocess.SubprocessError):
            raise refused('write_guard_probe_failed') from None
        finally:
            state.unlink(missing_ok=True)


def prepare(provider, binary, original_env, private, cwd, manifest, *, metadata=None):
    metadata = metadata if metadata is not None else {}
    origin = Path(original_env.get('HOME', str(Path.home())))
    home = private / 'home'; home.mkdir(mode=0o700)
    temp = private / 'tmp'; temp.mkdir(mode=0o700)
    # Do not inherit provider endpoints, API keys, config overrides, remote
    # control addresses, shell injection, or IDE integration environment.
    env = {k: v for k, v in original_env.items() if k in {'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE'}}
    env.update(HOME=str(home), TMPDIR=str(temp), XDG_CONFIG_HOME=str(home / '.config'),
               XDG_DATA_HOME=str(home / '.local/share'), XDG_CACHE_HOME=str(home / '.cache'))
    prompt = manifest['system_prompt'] + '\nApproved review input:\n' + manifest['user_prompt']
    if provider == 'agent':
        # Machine-managed hooks/settings cannot be redirected by HOME. Refuse
        # their presence, including team settings from the caller's account.
        managed = [Path('/Library/Application Support/Cursor'), Path('/etc/cursor'),
                   origin / '.cursor/managed']
        if any(p.exists() for p in managed):
            raise unsupported(provider, 'managed_policy', 'managed_policy_present')
        cursor_auth(origin, home)
        config = home / '.cursor'
        write_json(config / 'cli-config.json', dict(version=1, editor=dict(vimMode=False),
                   approvalMode='allowlist', sandbox=dict(mode='enabled', readBoundary='workspace'),
                   permissions=dict(allow=['Read(**)'], deny=['Write(**)', 'Shell(*)', 'Mcp(*:*)', 'WebFetch(*)'])))
        write_json(config / 'mcp.json', dict(mcpServers={}))
        write_json(config / 'hooks.json', dict(version=1, hooks={}))
        env.update(CURSOR_CONFIG_DIR=str(config), CURSOR_DATA_DIR=str(home / 'cursor-data'),
                   AGENT_CLI_CREDENTIAL_STORE='file')
        required = ['--print', '--mode', '--sandbox', '--model', '--output-format', '--workspace', '--trust']
        values = {'--mode': 'ask', '--sandbox': 'enabled', '--output-format': 'json'}
        argv = [binary, '--print', '--mode', 'ask', '--sandbox', 'enabled', '--trust', '--workspace', str(cwd),
                '--model', manifest['model'], '--output-format', 'json', '--', prompt]
    elif provider == 'agy':
        gemini = home / '.gemini'
        # The standalone subscription token, not Gemini API/ADC credentials or
        # history/state/config. Never copy the rest of the user's .gemini tree.
        credential(origin / '.gemini/jetski-standalone-oauth-token', gemini / 'jetski-standalone-oauth-token')
        write_json(gemini / 'antigravity-cli/settings.json', dict(toolPermission='strict',
                   enableTerminalSandbox=True, allowNonWorkspaceAccess=False,
                   permissions=dict(allow=[f'read_file({cwd})'], ask=[], deny=[
                       'write_file(*)', 'command(*)', 'unsandboxed(*)', 'mcp(*)',
                       'read_url(*)', 'execute_url(*)'])))
        required = ['--print', '--mode', '--sandbox', '--model', '--output-format', '--disable-slash-commands']
        values = {'--mode': 'plan', '--output-format': 'json'}
        argv = [binary, '--mode', 'plan', '--sandbox', '--disable-slash-commands',
                '--model', manifest['model'], '--output-format', 'json', '--print', prompt]
    else:
        raise refused()
    prefix = guard_prefix(private, cwd)
    probe_guard(prefix, env, private, cwd)
    discover(binary, env, cwd, provider=provider, prefix=prefix, required=required,
             values=values, metadata=metadata)
    return [*prefix, *argv], env
