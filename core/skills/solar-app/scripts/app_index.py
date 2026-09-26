"""Derived SQLite projection of the framework runtime, for the console and MCP.

Tasks come from solar-state. The audit, the gateway record and continuity are
still read from their files. Every row carries the fingerprint of the file it
came from, so a consumer can tell whether the projection is still valid.
Delete `index.sqlite` and it comes back from those same sources. The live
runtime's index is never deleted by this module.

Parsing is not duplicated: tasks reuse `app_solar`'s readers, so the console and
the index can never drift into two different ideas of the same file.

    python3 app_index.py build     # (re)build the projection
    python3 app_index.py hash      # content hash, ignoring build timestamps
    python3 app_index.py verify    # build, hash, delete, rebuild, compare
    python3 app_index.py stale     # sources that changed since the build
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import app_solar

SCHEMA_VERSION = 1
# Columns that record when the build happened. They never take part in the
# equivalence check: the plan says construction times are not content.
BUILD_COLUMNS = {'indexed_at', 'built_at'}

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    path TEXT PRIMARY KEY, kind TEXT NOT NULL, size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL, indexed_at TEXT NOT NULL);
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, title TEXT, state TEXT, created_at TEXT, timestamp TEXT,
    provider TEXT, provider_requested TEXT, origin TEXT, summary TEXT,
    artifacts TEXT, recurring INTEGER, recurring_run_count TEXT,
    recurring_last_run TEXT, stale INTEGER, file TEXT, source_path TEXT NOT NULL
        REFERENCES sources(path));
CREATE TABLE executions (
    router_id TEXT PRIMARY KEY, request_id TEXT, state TEXT, provider TEXT,
    user_id TEXT, origin TEXT, started_at TEXT, ended_at TEXT, duration_ms TEXT,
    summary TEXT, artifacts TEXT, source_path TEXT NOT NULL
        REFERENCES sources(path));
CREATE TABLE components (
    component TEXT PRIMARY KEY, state TEXT, cause_code TEXT, cause TEXT,
    observed_at TEXT, source_path TEXT);
CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE INDEX tasks_state ON tasks(state);
CREATE INDEX executions_state ON executions(state);
CREATE INDEX sources_kind ON sources(kind);
"""


def index_path() -> Path:
    return app_solar.runtime_dir('index.sqlite')


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


class _Sources:
    """Records every file the projection was derived from, with its fingerprint."""

    def __init__(self, stamp: str):
        self.rows: dict[str, tuple] = {}
        self.stamp = stamp

    def add(self, path: Path, kind: str) -> str:
        key = str(path)
        if key not in self.rows:
            try:
                stat = path.stat()
            except OSError:
                return key
            self.rows[key] = (key, kind, stat.st_size, stat.st_mtime_ns,
                              _digest(path), self.stamp)
        return key


def _task_sources(sources: _Sources, tasks: list[dict]) -> None:
    """Fingerprint state.sqlite, and any log the row already points at."""
    db = app_solar.solar_state.db_path()
    if db.is_file():
        sources.add(db, 'task')
        # WAL commits land in the sidecar. The main file can stay byte-identical
        # until a checkpoint, so a new task has to move this fingerprint too.
        for suffix in ('-wal', '-shm'):
            side = Path(str(db) + suffix)
            if side.is_file():
                sources.add(side, 'task')
    for row in tasks:
        log = row.get('log_path')
        if log and Path(log).is_file():
            sources.add(Path(log), 'task_log')


def _task_source_path(row: dict, workspace: Path) -> str:
    del row, workspace
    return str(app_solar.solar_state.db_path())


def _scan_audit() -> tuple[list[dict], dict]:
    """Full pass over the audit rows. The console reads only its tail."""
    records: dict[str, dict] = {}
    counters = dict(executions=0, router_errors=0, invalid=0)
    try:
        with app_solar.solar_state.session() as store:
            lines = store.audit_lines()
    except app_solar.solar_state.StateError:
        return [], counters
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not row.get('router_id'):
                raise ValueError('Missing router_id')
        except ValueError:
            counters['invalid'] += 1
            continue
        if row.get('event') == 'start':
            counters['executions'] += 1
        elif row.get('event') == 'end' and row.get('status') in ('error', 'failed'):
            counters['router_errors'] += 1
        item = records.setdefault(row['router_id'], {})
        item.update(row)
        if row.get('event') == 'start':
            item['started_at'] = row.get('ts')
        elif row.get('event') == 'end':
            item['ended_at'] = row.get('ts')
    runs = []
    for router_id, data in records.items():
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        result = data.get('result') if isinstance(data.get('result'), dict) else {}
        ended = bool(data.get('ended_at'))
        summary = str(data.get('error') or data.get('intention') or data.get('decision_kind') or '')
        runs.append(dict(
            router_id=router_id, request_id=data.get('request_id') or router_id,
            state=data.get('status', 'unknown') if ended else 'open',
            provider=data.get('provider'), user_id=data.get('user_id'),
            origin=data.get('channel') or metadata.get('origin_channel'),
            started_at=data.get('started_at'), ended_at=data.get('ended_at'),
            duration_ms=data.get('duration_ms'), summary=summary[:500],
            artifacts=result.get('artifacts') if isinstance(result.get('artifacts'), list) else [],
        ))
    runs.sort(key=lambda row: (app_solar.epoch(row['ended_at'] or row['started_at']) or 0,
                              row['router_id']), reverse=True)
    return runs, counters


def build(workspace: Path | None = None, target: Path | None = None) -> Path:
    """Build the projection into a temp file and move it into place atomically."""
    workspace = Path(workspace or os.environ.get('SOLAR_WORKSPACE') or Path.cwd()).resolve()
    target = Path(target or index_path())
    stamp = app_solar.iso()
    sources = _Sources(stamp)

    tasks, _ = app_solar.read_tasks(workspace)
    _task_sources(sources, tasks)

    audit_key = str(app_solar.solar_state.db_path())
    runs, counters = _scan_audit()

    gateway = app_solar.runtime_dir('gateway') / 'env.fail'
    stamp_file = app_solar.runtime_dir('gateway') / 'env.stamp'
    for path, kind in ((gateway, 'gateway'), (stamp_file, 'gateway')):
        if path.exists():
            sources.add(path, kind)

    snapshot = app_solar.snapshot(workspace)
    components = [row for row in snapshot['health']['components']
                  if row['component'] in ('storage', 'gateway', 'continuity')]

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.building')
    if temp.exists():
        temp.unlink()
    connection = sqlite3.connect(temp)
    try:
        connection.executescript(SCHEMA)
        connection.executemany('INSERT INTO sources VALUES (?,?,?,?,?,?)',
                               sorted(sources.rows.values()))
        connection.executemany(
            'INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [(row['id'], row['title'], row['state'], row['created_at'], row['timestamp'],
              row['provider'], row['provider_requested'], row['origin'], row['summary'],
              json.dumps(row['artifacts'], sort_keys=True), int(bool(row['recurring'])),
              row['recurring_run_count'], row['recurring_last_run'], int(bool(row['stale'])),
              row['file'], _task_source_path(row, workspace))
             for row in sorted(tasks, key=lambda row: row['id'])])
        connection.executemany(
            'INSERT OR REPLACE INTO executions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            [(row['router_id'], row['request_id'], row['state'], row['provider'],
              row['user_id'], row['origin'], row['started_at'], row['ended_at'],
              str(row['duration_ms']) if row['duration_ms'] is not None else None,
              row['summary'], json.dumps(row['artifacts'], sort_keys=True), audit_key)
             for row in sorted(runs, key=lambda row: row['router_id'])])
        connection.executemany(
            'INSERT OR REPLACE INTO components VALUES (?,?,?,?,?,?)',
            [(row['component'], row['state'], row.get('cause_code'), row.get('cause'),
              row.get('observed_at') if row['component'] != 'storage' else None,
              row.get('path')) for row in components])
        counts = snapshot['counts']
        connection.executemany('INSERT INTO counters VALUES (?,?)', sorted({
            'tasks': counts['tasks'], 'executions': counters['executions'],
            'errors': counts['errors'], 'recurring': counts['recurring'],
            'router_errors': counters['router_errors'],
            'audit_invalid': counters['invalid'],
            'executions_indexed': len(runs),
            **{'tasks_' + state: value for state, value in counts['task_states'].items()},
        }.items()))
        connection.executemany('INSERT INTO meta VALUES (?,?)', sorted({
            'schema_version': str(SCHEMA_VERSION),
            'runtime_root': str(app_solar.runtime_dir()),
            'workspace': str(workspace),
            'source_of_truth': 'files',
            'built_at': stamp,
        }.items()))
        connection.commit()
    finally:
        connection.close()
    os.replace(temp, target)
    return target


def content_hash(target: Path | None = None) -> str:
    """Hash every row of every table, skipping the build timestamps."""
    target = Path(target or index_path())
    connection = sqlite3.connect(f'file:{target}?mode=ro', uri=True)
    try:
        digest = hashlib.sha256()
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info({table})')
                       if row[1] not in BUILD_COLUMNS]
            digest.update(f'\n# {table}: {",".join(columns)}\n'.encode())
            selection = ','.join(f'"{column}"' for column in columns)
            rows = connection.execute(
                f'SELECT {selection} FROM "{table}" ORDER BY {selection}')
            for row in rows:
                if table == 'meta' and row and row[0] == 'built_at':
                    continue
                digest.update(repr(row).encode() + b'\n')
        return digest.hexdigest()
    finally:
        connection.close()


def stale_sources(target: Path | None = None) -> list[dict]:
    """What a consumer checks before trusting the projection."""
    target = Path(target or index_path())
    connection = sqlite3.connect(f'file:{target}?mode=ro', uri=True)
    try:
        recorded = {row[0]: row for row in connection.execute(
            'SELECT path, kind, size, mtime_ns, sha256 FROM sources')}
    finally:
        connection.close()
    changed = []
    for path, (_, kind, size, mtime_ns, sha) in recorded.items():
        file = Path(path)
        try:
            stat = file.stat()
        except OSError:
            changed.append(dict(path=path, kind=kind, reason='missing'))
            continue
        if stat.st_size != size or stat.st_mtime_ns != mtime_ns:
            changed.append(dict(path=path, kind=kind,
                                reason='rewritten' if _digest(file) != sha else 'touched'))
    return changed


def snapshot_from_index(workspace: Path, target: Path | None = None) -> dict:
    """The console's shape, served from the projection instead of the files."""
    target = Path(target or index_path())
    connection = sqlite3.connect(f'file:{target}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tasks = [dict(
            id=row['id'], title=row['title'], state=row['state'], source='task',
            summary=row['summary'], timestamp=row['timestamp'], created_at=row['created_at'],
            provider=row['provider'], provider_requested=row['provider_requested'],
            origin=row['origin'], artifacts=json.loads(row['artifacts'] or '[]'),
            file=row['file'], recurring=bool(row['recurring']),
            recurring_run_count=row['recurring_run_count'],
            recurring_last_run=row['recurring_last_run'], stale=bool(row['stale']),
        ) for row in connection.execute('SELECT * FROM tasks')]
        runs = [dict(
            id=row['router_id'], title=row['request_id'], source='router',
            state=row['state'], summary=row['summary'], timestamp=row['ended_at'] or row['started_at'],
            provider=row['provider'], user_id=row['user_id'], origin=row['origin'],
            artifacts=json.loads(row['artifacts'] or '[]'), duration_ms=row['duration_ms'],
            history_turns=None, summary_used=None, stale=False, file=row['source_path'],
        ) for row in connection.execute(
            'SELECT * FROM executions ORDER BY COALESCE(ended_at, started_at) DESC LIMIT ?',
            (app_solar.PAGE_SIZE,))]
        counts = {name: value for name, value in connection.execute(
            'SELECT name, value FROM counters')}
        components = [dict(component=row['component'], state=row['state'],
                           cause_code=row['cause_code'], cause=row['cause'], detail='',
                           observed_at=row['observed_at'], path=row['source_path'])
                      for row in connection.execute('SELECT * FROM components')]
        meta = {key: value for key, value in connection.execute('SELECT key, value FROM meta')}
    finally:
        connection.close()

    tasks.sort(key=lambda row: app_solar.epoch(row['timestamp']) or 0, reverse=True)
    checked = time.time()
    storage_ok = not any(row['state'] == 'problems' for row in components)
    status = ('problems' if any(row['state'] == 'problems' for row in components)
              else 'unverified' if any(row['state'] == 'unverified' for row in components)
              else 'healthy')
    health = dict(status=status, storage_ok=storage_ok, checked_at=app_solar.iso(checked),
                  fresh_until=app_solar.iso(checked + app_solar.FRESH_SECONDS),
                  components=components)
    return dict(
        workspace=str(workspace), solar_root=meta.get('runtime_root', ''),
        checked_at=app_solar.iso(checked),
        fresh_until=app_solar.iso(checked + app_solar.FRESH_SECONDS),
        health=health, tasks=tasks[:app_solar.PAGE_SIZE], executions=runs,
        activity=sorted(tasks + runs, key=lambda row: app_solar.epoch(row['timestamp']) or 0,
                        reverse=True)[:app_solar.PAGE_SIZE],
        counts=dict(
            tasks=counts.get('tasks', len(tasks)), executions=counts.get('executions', 0),
            errors=counts.get('errors', 0), recurring=counts.get('recurring', 0),
            task_states={state: counts.get('tasks_' + state, 0)
                         for state in app_solar.TASK_STATES}),
        working=sum(row['state'] == 'active' for row in tasks + runs),
    )


def projection(workspace: Path, target: Path | None = None) -> dict:
    """The console reads the views in state.sqlite. index.sqlite is not the source."""
    del target
    data = app_solar.snapshot(workspace)
    data['projection'] = dict(
        source='state', index=str(app_solar.solar_state.db_path()), available=True,
        stale=[], reason='')
    return data


def counters(target: Path | None = None) -> dict:
    target = Path(target or index_path())
    connection = sqlite3.connect(f'file:{target}?mode=ro', uri=True)
    try:
        return {name: value for name, value in connection.execute(
            'SELECT name, value FROM counters ORDER BY name')}
    finally:
        connection.close()


def _report(target: Path) -> dict:
    connection = sqlite3.connect(f'file:{target}?mode=ro', uri=True)
    try:
        rows = {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for table in ('sources', 'tasks', 'executions', 'components', 'counters')}
    finally:
        connection.close()
    return dict(rows=rows, counters=counters(target), hash=content_hash(target))


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else 'build'
    workspace = Path(os.environ.get('SOLAR_WORKSPACE') or Path.cwd())
    target = index_path()
    if command == 'build':
        build(workspace, target)
        print(json.dumps(dict(index=str(target), **_report(target)), indent=2, sort_keys=True))
    elif command == 'hash':
        print(content_hash(target))
    elif command == 'stale':
        print(json.dumps(stale_sources(target), indent=2, sort_keys=True))
    elif command == 'verify':
        build(workspace, target)
        before = _report(target)
        fingerprints_before = sqlite3.connect(f'file:{target}?mode=ro', uri=True).execute(
            'SELECT path, sha256 FROM sources ORDER BY path').fetchall()
        target.unlink()
        deleted = not target.exists()
        time.sleep(1.1)  # a different build second, so equality cannot be an artefact
        build(workspace, target)
        after = _report(target)
        fingerprints_after = sqlite3.connect(f'file:{target}?mode=ro', uri=True).execute(
            'SELECT path, sha256 FROM sources ORDER BY path').fetchall()
        print(json.dumps(dict(
            deleted=deleted, identical=before['hash'] == after['hash'],
            sources_unchanged=fingerprints_before == fingerprints_after,
            before=before, after=after), indent=2, sort_keys=True))
        return 0 if before['hash'] == after['hash'] and deleted else 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
