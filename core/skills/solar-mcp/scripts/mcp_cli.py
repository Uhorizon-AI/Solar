#!/usr/bin/env python3
"""Serve Solar MCP; print, install or uninstall user-level client registrations.

Registration requires Python 3.11+; stdio does not load the TOML parser.
Registration validates and preserves a stable interpreter path for GUI clients.
    solar mcp
    solar mcp print --workspace PATH
    solar mcp install [--workspace PATH] [--clients cursor,claude,codex] [--dry-run]
    solar mcp uninstall [--clients cursor,claude,codex] [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from functools import lru_cache

def toml_parser():
    try:
        import tomllib
    except ImportError as exc:
        raise ValueError('Solar MCP registration requires Python 3.11 or newer.') from exc
    return tomllib


def registration_python() -> str:
    candidate = os.environ.get('SOLAR_MCP_PYTHON') or shutil.which('python3')
    if not candidate:
        raise ValueError('Set SOLAR_MCP_PYTHON to a stable Python 3.11+ interpreter.')
    # Preserve the stable symlink, but inspect the interpreter it launches.
    candidate = os.path.abspath(os.path.expanduser(candidate))
    try:
        result = subprocess.run([candidate, '-c',
            'import sys,json; print(json.dumps([list(sys.version_info[:2]),sys.prefix != sys.base_prefix]))'],
            capture_output=True, text=True, timeout=10)
        version, virtualenv = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError('Cannot validate SOLAR_MCP_PYTHON interpreter.') from exc
    if result.returncode or version < [3, 11] or virtualenv:
        raise ValueError('Registration needs a stable, non-venv Python 3.11+ interpreter.')
    return candidate


SERVER_KEY = 'solar'
SCRIPT_DIR = Path(__file__).resolve().parent
MCP_SERVER = SCRIPT_DIR / 'mcp_server.py'


def solar_bin() -> str:
    found = shutil.which('solar')
    candidate = Path(found) if found else Path.home() / '.local/bin/solar'
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.absolute())
    candidate = SCRIPT_DIR.parents[1] / 'solar-client/scripts/solar'
    print(f'NOTE: using checkout dispatcher {candidate}; keep this checkout in place.', file=sys.stderr)
    return str(candidate)


def workspace_path(explicit: str | None) -> Path:
    resolver = SCRIPT_DIR.parents[1] / 'solar-paths/scripts/resolve_solar_paths.sh'
    # Pass paths as argv, never interpolate them into shell source.
    argv = ['bash', '-c', 'source "$1"; shift; solar_resolve_paths --export "$@"',
            'solar-mcp', str(resolver)]
    if explicit:
        argv += ['--workspace', str(Path(explicit).expanduser().resolve())]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode:
        raise ValueError((proc.stderr or proc.stdout).strip() + '\nSpecify --workspace PATH.')
    values = dict(line.split('=', 1) for line in proc.stdout.splitlines() if '=' in line)
    ws = Path(values.get('SOLAR_WORKSPACE', '/nonexistent')).resolve()
    if not (ws / '.solar/settings.json').is_file() or not (ws / 'sun').is_dir():
        raise ValueError(f'Invalid Solar workspace: {ws}; expected .solar/settings.json and sun/.')
    return ws


def entry(workspace: Path) -> dict:
    interpreter = registration_python()
    return dict(command=solar_bin(), args=['mcp'], env={
        'SOLAR_WORKSPACE': str(workspace), 'SOLAR_MCP_PYTHON': interpreter})


def toml_block(workspace: Path, registration=None) -> str:
    toml_parser()
    e = registration if registration is not None else entry(workspace)
    quote = lambda s: json.dumps(s, ensure_ascii=False)
    return ('[mcp_servers.solar]\n' + f'command = {quote(e["command"])}\n'
            'args = ["mcp"]\nenabled = true\n\n[mcp_servers.solar.env]\n' +
            ''.join(f'{key} = {quote(value)}\n' for key, value in e['env'].items()))


def _header_path(line: str) -> tuple[str, ...] | None:
    """Let the TOML parser interpret quoted keys, comments and array headers."""
    tomllib = toml_parser()
    if not line.lstrip().startswith('['):
        return None
    try:
        node = tomllib.loads(line)
    except tomllib.TOMLDecodeError:
        return None
    keys = []
    while isinstance(node, dict) and len(node) == 1:
        key, node = next(iter(node.items()))
        keys.append(key)
    return tuple(keys) or None


def upsert_toml_table(text: str, prefix: str, block: str) -> str:
    tomllib = toml_parser()
    original = tomllib.loads(text)
    wanted = tuple(prefix.split('.'))
    expected = copy.deepcopy(original)
    parent = expected
    for key in wanted[:-1]:
        parent = parent.setdefault(key, {})
    if block:
        replacement = tomllib.loads(block)
        for key in wanted:
            replacement = replacement[key]
        if parent.get(wanted[-1]) == replacement:
            return text
        parent[wanted[-1]] = replacement
    else:
        if wanted[-1] not in parent:
            return text
        del parent[wanted[-1]]
    kept, previous = [], []
    skipping = False
    for line in text.splitlines(True):
        header = _header_path(line)
        if header:
            try:
                # An apparent header inside a multiline string is not a boundary.
                tomllib.loads(''.join(previous))
            except tomllib.TOMLDecodeError:
                header = None
        if header:
            skipping = header[:len(wanted)] == wanted
        if not skipping:
            kept.append(line)
        previous.append(line)
    result = ''.join(kept).rstrip() + '\n'
    if block:
        result += '\n' + block.rstrip() + '\n'
    actual = tomllib.loads(result)
    # Reject unsupported layouts (e.g. inline tables) instead of losing data.
    def prune(value):
        if isinstance(value, dict):
            return {k: prune(v) for k, v in value.items() if v != {}}
        return value
    if prune(actual) != prune(expected):
        raise ValueError('Cannot safely edit this TOML layout; configuration unchanged.')
    return result


def client_paths() -> dict[str, Path]:
    home = Path.home()
    return {'cursor': home / '.cursor/mcp.json', 'claude': home / '.claude.json',
            'codex': Path(os.environ.get('CODEX_HOME', str(home / '.codex'))) / 'config.toml'}


def _read(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ValueError(f'Refusing symlink configuration: {path}')
    return path.read_bytes() if path.exists() else None


def _replace(path: Path, content: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@lru_cache(maxsize=1)
def runtime_module():
    scripts = str(SCRIPT_DIR.parents[1] / 'solar-paths/scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import solar_runtime
    return solar_runtime


def write_config(path: Path, before: bytes | None, after: bytes, dry_run: bool) -> str:
    if before == after:
        return f'UNCHANGED: {path}'
    if dry_run:
        # Do not expose unrelated credentials from the existing configuration.
        def registration(raw):
            if not raw:
                return {}
            data = toml_parser().loads(raw.decode()) if path.suffix == '.toml' else json.loads(raw)
            solar = (data.get('mcp_servers' if path.suffix == '.toml' else 'mcpServers') or {}).get('solar', {})
            solar = copy.deepcopy(solar)
            if isinstance(solar.get('env'), dict):
                solar['env'] = {key: value if key in ('SOLAR_WORKSPACE', 'SOLAR_MCP_PYTHON') else '<redacted>'
                                for key, value in solar['env'].items()}
            return solar
        old = json.dumps(registration(before), indent=2).splitlines(True)
        new = json.dumps(registration(after), indent=2).splitlines(True)
        diff = ''.join(difflib.unified_diff(old, new, fromfile='solar (before)', tofile='solar (after)'))
        return f'WOULD UPDATE: {path}\n{diff}'
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cooperating Solar writers share a lock. Other apps do not; check again
    # immediately before replacement and fail closed on an observed change.
    import fcntl
    import hashlib
    lock_root = runtime_module().runtime_dir('mcp') / 'config-locks'
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / (hashlib.sha256(str(path.resolve()).encode()).hexdigest() + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _read(path) != before:
            raise ValueError(f'Concurrent configuration change: {path}; retry.')
        mode = stat.S_IMODE(path.stat().st_mode) if before is not None else 0o600
        if before is not None:
            backup = path.with_name(path.name + '.bak.solar-mcp')
            if backup.is_symlink():
                raise ValueError(f'Refusing symlink backup: {backup}')
            _replace(backup, before, 0o600)
        if _read(path) != before:
            raise ValueError(f'Concurrent configuration change: {path}; retry.')
        _replace(path, after, mode)
    return f'OK: {path}'


def merge_json_servers(path: Path, server: dict | None, *, create: bool, dry_run=False) -> str:
    before = _read(path)
    if before is None and not create:
        raise FileNotFoundError(str(path))
    data = json.loads(before) if before else {}
    if not isinstance(data, dict) or not isinstance(data.get('mcpServers', {}), dict):
        raise ValueError(f'{path}: expected object with mcpServers object')
    servers = data.setdefault('mcpServers', {})
    if server is None:
        if SERVER_KEY not in servers:
            return f'UNCHANGED: {path}'
        del servers[SERVER_KEY]
    elif servers.get(SERVER_KEY) == server:
        return f'UNCHANGED: {path}'
    else:
        servers[SERVER_KEY] = server
    after = (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()
    return write_config(path, before, after, dry_run)


def merge_codex_toml(path: Path, workspace: Path | None, *, create: bool, dry_run=False, registration=None) -> str:
    before = _read(path)
    if before is None and not create:
        raise FileNotFoundError(str(path))
    result = upsert_toml_table((before or b'').decode(), 'mcp_servers.solar',
                               toml_block(workspace, registration) if workspace is not None else '')
    return write_config(path, before, result.encode(), dry_run)


def print_snippets(workspace: Path, registration=None) -> None:
    registration = entry(workspace) if registration is None else registration
    for name, path in client_paths().items():
        print(f'=== {name}: {path} ===')
        print(toml_block(workspace, registration) if name == 'codex' else json.dumps(
            {'mcpServers': {SERVER_KEY: dict(registration, type='stdio') if name == 'claude' else registration}}, indent=2))


def install(workspace: Path | None, names: list[str], *, dry_run=False, uninstall=False, registration=None) -> int:
    if not uninstall and registration is None:
        registration = entry(workspace)
    failed = 0
    for name in dict.fromkeys(names):
        path = client_paths()[name]
        try:
            create = not uninstall and name != 'claude'
            if name == 'codex':
                result = merge_codex_toml(path, None if uninstall else workspace,
                                          create=create, dry_run=dry_run, registration=registration)
            else:
                server = None if uninstall else (dict(registration, type='stdio') if name == 'claude' else registration)
                result = merge_json_servers(path, server, create=create, dry_run=dry_run)
            print(result)
        except FileNotFoundError:
            print(f'SKIP: {name} (no {path})')
        except (OSError, ValueError) as exc:
            print(f'ERROR: {name}: {exc}', file=sys.stderr)
            failed += 1
    return int(bool(failed))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv == ['serve']:
        os.execv(sys.executable, [sys.executable, str(MCP_SERVER)])
    parser = argparse.ArgumentParser(prog='solar mcp', description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('print', 'install', 'uninstall'):
        command = sub.add_parser(name)
        if name != 'uninstall':
            command.add_argument('--workspace')
        if name != 'print':
            command.add_argument('--clients', default='cursor,claude,codex')
            command.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        toml_parser()
        names = [n.strip().lower() for n in getattr(args, 'clients', '').split(',') if n.strip()]
        if args.cmd != 'print' and (not names or any(n not in client_paths() for n in names)):
            raise ValueError('Choose clients from cursor,claude,codex. Gemini is not supported yet.')
        ws = None if args.cmd == 'uninstall' else workspace_path(args.workspace)
        registration = None if args.cmd == 'uninstall' else entry(ws)
        if args.cmd == 'print':
            print_snippets(ws, registration)
            return 0
        return install(ws, names, dry_run=args.dry_run, uninstall=args.cmd == 'uninstall', registration=registration)
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
