"""Read the canonical task files and router audit without creating an App store."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

FRESH_SECONDS = 120
STALE_SECONDS = 86400
TASK_STATES = ('drafts', 'queued', 'active', 'error', 'completed', 'cancelled')
PAGE_SIZE = 40
_AUDIT_INDEX = {}


def iso(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp, timezone.utc).isoformat()


def epoch(value):
    try:
        if isinstance(value, (float, int)) or str(value).isdigit():
            return float(value)
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def fields(text):
    """Parse the scalar frontmatter contract used by the task executor."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        raise ValueError('Missing task frontmatter')
    data = {}
    for line in lines[1:]:
        if line.strip() == '---':
            return data
        key, sep, value = line.partition(':')
        if sep and key and not key[0].isspace():
            data[key.strip()] = value.strip().strip('"').strip("'")
    raise ValueError('Unclosed task frontmatter')


def issue(component, cause_code, detail='', path='', state='warning', observed_at=None):
    return dict(component=component, cause_code=cause_code, cause=detail or cause_code,
                detail=detail, path=str(path), state=state, observed_at=observed_at)


def result_summary(text, data):
    for heading in ('Execution Error', 'Error', 'Result', 'Resultado'):
        match = re.search(r'^## '+heading+r'\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        if match:
            return ' '.join(match.group(1).split())[:500]
    return str(data.get('summary') or data.get('description') or '')[:500]


def artifacts(text, data):
    """Expose only paths explicitly recorded as outputs, never guessed artifacts."""
    result = []
    for key in ('artifact', 'artifact_path', 'output_file', 'output_path', 'artifacts'):
        if data.get(key):
            result.append(data[key])
    for section in re.findall(r'^## (?:Result|Resultado|Artifacts|Artefactos)\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S):
        result.extend(re.findall(r'\[[^\]]+\]\(([^)]+)\)', section))
    # The execution log's Result may contain nested headings. Only explicit
    # output statements count as produced artifacts, not arbitrary source paths.
    for line in text.splitlines():
        if re.search(r'(guardad[oa] en|saved (?:to|at)|output(?: file)?|artefact[os]*|artifact[ s]*)', line, re.I):
            result.extend(re.findall(r'`((?:sun/|planets/|/)[^`]+)`', line))
    return list(dict.fromkeys(result))


def read_tasks(workspace):
    root = workspace / 'sun/runtime/async-tasks'
    jobs, problems = [], []
    try:
        # A real directory read, not exists() or a process check.
        available = {p.name for p in root.iterdir()}
    except OSError as exc:
        return [], [issue('tasks', 'storage_unreadable', str(exc), root, 'problems')]
    for state in TASK_STATES:
        if state not in available:
            continue
        try:
            paths = [p for p in (root / state).iterdir() if p.suffix == '.md']
            for path in paths:
                try:
                    text = path.read_text(encoding='utf-8')
                    data = fields(text)
                    stamp = path.stat().st_mtime
                    created = epoch(data.get('created'))
                    log = root / 'logs' / (path.stem + '.log')
                    log_text = ''
                    try:
                        log_text = log.read_text(encoding='utf-8')
                        log_id = re.search(r'^- task_id: (.+)$', log_text, re.M)
                        if log_id and log_id.group(1) not in (data.get('id'), path.stem):
                            log_text = ''
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        problems.append(issue('task log', 'record_unreadable', str(exc), log))
                    used = re.search(r'^- provider_used: (.+)$', log_text, re.M)
                    provider = data.get('provider_used') or (used.group(1) if used else None)
                    jobs.append(dict(
                        id=data.get('id') or path.stem, title=data.get('title') or path.stem,
                        state=state, source='task', summary=result_summary(log_text, data) or result_summary(text, data),
                        timestamp=iso(stamp), created_at=data.get('created'),
                        provider=provider, provider_requested=data.get('provider'),
                        origin=data.get('origin_channel'), origin_thread_id=data.get('origin_thread_id'),
                        artifacts=artifacts(text+'\n'+log_text, data), file=str(path.relative_to(workspace)),
                        recurring=data.get('recurring') == 'true', recurring_run_count=data.get('recurring_run_count'),
                        recurring_last_run=data.get('recurring_last_run'),
                        stale=state == 'drafts' and created is not None and time.time()-created > STALE_SECONDS,
                    ))
                except (OSError, ValueError) as exc:
                    problems.append(issue('tasks', 'record_invalid', str(exc), path))
        except OSError as exc:
            problems.append(issue('tasks', 'storage_unreadable', str(exc), root / state, 'problems'))
    jobs.sort(key=lambda row: epoch(row['timestamp']) or 0, reverse=True)
    return jobs, problems


def _audit_lines_from_tail(path, wanted):
    """Read only as far back as needed to assemble the requested page."""
    with path.open('rb') as stream:
        end = stream.seek(0, 2)
        buffer = b''
        rows = []
        ids = set()
        while end > 0 and len(ids) < wanted:
            size = min(65536, end)
            end -= size
            stream.seek(end)
            buffer = stream.read(size) + buffer
            parts = buffer.splitlines()
            if end and parts:
                buffer = parts.pop(0)
            else:
                buffer = b''
            for raw in reversed(parts):
                rows.append(raw.decode('utf-8', errors='replace'))
                try:
                    rid = json.loads(raw).get('router_id')
                    if rid:
                        ids.add(rid)
                except (ValueError, AttributeError):
                    pass
        return list(reversed(rows))


def audit_counts(path):
    """Maintain complete counters by parsing only bytes appended since the last call."""
    try:
        stat = path.stat()
        key = str(path.resolve())
        cached = _AUDIT_INDEX.get(key)
        if not cached or cached['inode'] != stat.st_ino or stat.st_size < cached['position']:
            cached = dict(inode=stat.st_ino, position=0, total=0, errors=0, invalid=0, partial=b'')
        with path.open('rb') as stream:
            stream.seek(cached['position'])
            data = cached['partial'] + stream.read()
            lines = data.split(b'\n')
            cached['partial'] = lines.pop() if lines else b''
            for raw in lines:
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                    if row.get('event') == 'start':
                        cached['total'] += 1
                    elif row.get('event') == 'end' and row.get('status') in ('error', 'failed'):
                        cached['errors'] += 1
                except (ValueError, AttributeError):
                    cached['invalid'] += 1
            cached['position'] = stat.st_size
            _AUDIT_INDEX[key] = cached
        return cached
    except OSError:
        return dict(total=0, errors=0, invalid=0)


def read_router(workspace, limit=PAGE_SIZE, offset=0, state=None):
    if state:
        wanted = offset + limit
        window = max(wanted * 2, PAGE_SIZE)
        while True:
            candidates, problems = read_router(workspace, window, 0)
            matches = [row for row in candidates if (
                'completed' if row['state'] == 'success' else
                'error' if row['state'] == 'failed' else row['state']) == state]
            if len(matches) >= wanted or len(candidates) < window:
                return matches[offset:wanted], problems
            window *= 2
    path = workspace / 'sun/runtime/router/audit.jsonl'
    records, problems = {}, []
    try:
        lines = _audit_lines_from_tail(path, offset + limit)
        for number, line in enumerate(lines, 1):
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not row.get('router_id'):
                    raise ValueError('Missing router_id')
                item = records.setdefault(row['router_id'], {})
                item.update(row)
                if row.get('event') == 'start':
                    item['started_at'] = row.get('ts')
                elif row.get('event') == 'end':
                    item['ended_at'] = row.get('ts')
            except ValueError as exc:
                problems.append(issue('router audit', 'record_invalid', f'Tail record {number}: {exc}', path))
    except OSError as exc:
        problems.append(issue('router audit', 'storage_unreadable', str(exc), path, 'problems'))
    runs = []
    for rid, data in records.items():
        ended = bool(data.get('ended_at'))
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        stamp = data.get('ended_at') or data.get('started_at')
        age = time.time()-(epoch(stamp) or 0)
        result = data.get('result') if isinstance(data.get('result'), dict) else {}
        summary = str(data.get('error') or data.get('intention') or data.get('decision_kind') or '')
        timeout = re.search(r'timed out after ([0-9.]+) seconds', summary)
        if timeout:
            summary = 'Execution timed out after ' + timeout.group(1) + ' seconds'
        runs.append(dict(
            id=rid, title=data.get('request_id') or rid, source='router',
            state=data.get('status', 'unknown') if ended else ('active' if age <= FRESH_SECONDS else 'unverified'),
            summary=summary[:500],
            timestamp=stamp, provider=data.get('provider'), user_id=data.get('user_id'),
            origin=data.get('channel') or metadata.get('origin_channel'),
            artifacts=result.get('artifacts') if isinstance(result.get('artifacts'), list) else [],
            history_turns=data.get('history_turns'), summary_used=data.get('summary_used'),
            duration_ms=data.get('duration_ms'), stale=not ended and age > FRESH_SECONDS,
            file=str(path.relative_to(workspace)),
        ))
    runs.sort(key=lambda row: epoch(row['timestamp']) or 0, reverse=True)
    return runs[offset:offset + limit], problems


def snapshot(workspace):
    started = time.time()
    tasks, task_problems = read_tasks(workspace)
    runs, router_problems = read_router(workspace)
    audit = audit_counts(workspace / 'sun/runtime/router/audit.jsonl')
    if audit['invalid'] and not router_problems:
        router_problems.append(issue('router audit', 'record_invalid',
                                     f"{audit['invalid']} malformed record(s)",
                                     workspace / 'sun/runtime/router/audit.jsonl'))
    problems = task_problems + router_problems
    components = []
    gateway = workspace / 'sun/runtime/gateway/env.fail'
    try:
        raw = gateway.read_text(encoding='utf-8')
        data = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        failed = epoch(data.get('failed_at'))
        components.append(dict(component='gateway', state='problems', cause_code='gateway_failure',
            cause=data.get('reason') or 'Recorded gateway failure', detail=data.get('reason') or '', observed_at=iso(failed) if failed else None,
            attempts=data.get('attempts'), exhausted=data.get('exhausted') == '1',
            next_retry_at=iso(epoch(data['next_retry_at'])) if epoch(data.get('next_retry_at')) else None,
            stale=failed is None or started-failed > STALE_SECONDS, path=str(gateway.relative_to(workspace))))
    except FileNotFoundError:
        components.append(issue('gateway', 'gateway_unverified', 'No recent gateway probe', state='unverified'))
    except (OSError, ValueError) as exc:
        problems.append(issue('gateway record', 'record_invalid', str(exc), gateway))
    continuity = workspace / 'sun/runtime/continuity/active.json'
    try:
        data = json.loads(continuity.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Expected a continuity object')
        updated = epoch(data.get('updated_at'))
        stale = updated is None or started-updated > STALE_SECONDS
        components.append(dict(component='continuity', state='stale' if stale else 'observed', cause_code='continuity_state',
            cause=str(data.get('active_task') or 'No active intention'), detail='', observed_at=data.get('updated_at'),
            stale=stale, path=str(continuity.relative_to(workspace))))
    except FileNotFoundError:
        components.append(issue('continuity', 'continuity_unverified', 'No continuity record', state='unverified'))
    except (OSError, ValueError) as exc:
        problems.append(issue('continuity', 'record_invalid', str(exc), continuity))
    storage_ok = not any(row['state'] == 'problems' for row in problems)
    components.insert(0, dict(component='storage', state='healthy' if storage_ok else 'problems',
        cause_code='storage_readable' if storage_ok else 'storage_unreadable',
        cause='Task files and router audit are readable' if storage_ok else 'Canonical storage is not readable', detail='',
        observed_at=iso(), path=str(workspace / 'sun/runtime')))
    components.extend(problems)
    status = 'problems' if any(c['state']=='problems' for c in components) else 'unverified' if any(c['state']=='unverified' for c in components) else 'healthy'
    checked = time.time()
    return dict(workspace=str(workspace), solar_root=os.environ.get('SOLAR_ROOT', str(Path(__file__).resolve().parents[4])),
        checked_at=iso(checked), fresh_until=iso(checked+FRESH_SECONDS),
        health=dict(status=status, storage_ok=storage_ok, checked_at=iso(checked), fresh_until=iso(checked+FRESH_SECONDS), components=components),
        tasks=tasks[:PAGE_SIZE], executions=runs,
        activity=sorted(tasks+runs, key=lambda row: epoch(row['timestamp']) or 0, reverse=True)[:PAGE_SIZE],
        counts=dict(tasks=len(tasks), executions=audit['total'],
                    errors=sum(row['state'] in ('error', 'failed') for row in tasks) + audit['errors'],
                    recurring=sum(bool(row.get('recurring')) for row in tasks),
                    task_states={state: sum(row['state'] == state for row in tasks) for state in TASK_STATES}),
        working=sum(row['state']=='active' for row in tasks+runs),
    )


def activity_page(workspace, source='', state='', offset=0, limit=PAGE_SIZE):
    tasks, _ = read_tasks(workspace)
    if state:
        tasks = [row for row in tasks if row['state'] == state]
    runs, _ = read_router(workspace, limit=offset + limit + 1, state=state or None)
    items = tasks if source == 'task' else runs if source == 'router' else tasks + runs
    items.sort(key=lambda row: epoch(row['timestamp']) or 0, reverse=True)
    return dict(items=items[offset:offset + limit], offset=offset, limit=limit,
                has_more=len(items) > offset + limit)
