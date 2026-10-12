"""Confined, read-only access to explicitly published planet reports."""
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote

CLIENT = Path(__file__).resolve().parents[2] / 'solar-client/scripts'
if str(CLIENT) not in sys.path:
    sys.path.insert(0, str(CLIENT))
from skill_inventory import settings

MAX_INDEX = 128 * 1024
MAX_REPORT = 4 * 1024 * 1024
NAME = re.compile(r'[a-zA-Z0-9_-]+\Z')


def bounded_read(path, limit):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Published file exceeds size limit')
    return data


def confined(planet, relative, suffixes):
    if not isinstance(relative, str):
        raise ValueError('Invalid published path')
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != 'operations':
        raise ValueError('Published path must stay inside planet operations')
    target = (planet / rel).resolve(strict=True)
    if not target.is_relative_to(planet.resolve()) or target.suffix.lower() not in suffixes or not target.is_file():
        raise ValueError('Published path escapes its allowed scope')
    return target


def manifests(workspace):
    workspace = Path(workspace).resolve()
    excluded = set(settings(workspace).get('sync_exclude_planets', []))
    for planet in sorted((workspace / 'planets').glob('*')):
        if planet.name in excluded or not NAME.fullmatch(planet.name):
            continue
        if not planet.resolve().is_relative_to(workspace / 'planets'):
            continue
        index = planet / 'operations/leadership/reports/index.json'
        if not index.is_file():
            continue
        try:
            if not index.resolve().is_relative_to(planet.resolve()):
                raise ValueError('Report index escapes planet')
            data = json.loads(bounded_read(index, MAX_INDEX))
            if not isinstance(data, dict) or data.get('version') != 1:
                raise ValueError('Unsupported report index')
            rows, evidence = data.get('reports'), data.get('evidence', [])
            if not isinstance(rows, list) or len(rows) > 30 or not isinstance(evidence, list) or len(evidence) > 500:
                raise ValueError('Invalid report index limits')
            validated = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('Invalid report entry')
                for key in ('path', 'title', 'owner', 'generated_at', 'period', 'coverage', 'next_decision'):
                    if not isinstance(row.get(key), str) or len(row[key]) > 2000:
                        raise ValueError('Invalid report metadata')
                confined(planet, row['path'], {'.html'})
                validated.append(row)
            for relative in evidence:
                confined(planet, relative, {'.md', '.txt'})
            yield planet, dict(reports=validated, evidence=evidence), None
        except (OSError, ValueError, TypeError) as exc:
            yield planet, None, type(exc).__name__


def report_index(workspace):
    reports, errors = [], []
    for planet, data, error in manifests(workspace):
        if error:
            errors.append({'planet': planet.name, 'error': error})
            continue
        for row in data['reports']:
            reports.append({**row, 'planet': planet.name,
                            'href': '/reports/' + quote(planet.name, safe='') + '/' + quote(row['path'], safe='/')})
    return {'reports': reports, 'errors': errors}


def published_file(workspace, request_path):
    path = unquote(request_path)
    parts = path.split('/', 3)
    if len(parts) != 4 or parts[:2] != ['', 'reports'] or not NAME.fullmatch(parts[2]):
        raise ValueError('Invalid report request')
    name, relative = parts[2:]
    for planet, data, error in manifests(workspace):
        if planet.name != name or error:
            continue
        html_paths = {row['path'] for row in data['reports']}
        if relative not in html_paths and relative not in data['evidence']:
            raise ValueError('File is not explicitly published')
        target = confined(planet, relative, {'.html'} if relative in html_paths else {'.md', '.txt'})
        return bounded_read(target, MAX_REPORT), ('text/html' if relative in html_paths else 'text/plain') + '; charset=utf-8'
    raise ValueError('Report is not available')
