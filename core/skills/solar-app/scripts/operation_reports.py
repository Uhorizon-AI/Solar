"""Confined, read-only access to explicitly published planet reports."""
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

CLIENT = Path(__file__).resolve().parents[2] / 'solar-client/scripts'
INVENTORY = CLIENT / 'skill_inventory.py'

MAX_INDEX = 128 * 1024
MAX_REPORT = 4 * 1024 * 1024
NAME = re.compile(r'[a-zA-Z0-9_-]+\Z')
OPERATIONS = 'operations'
INDEX_RELATIVE = 'operations/leadership/reports/index.json'
INVALID_INDEX = 'index_unreadable'
DASHBOARDS_RELATIVE = 'operations/leadership/dashboards.json'

_inventory = None


class PublicationUnavailable(ValueError):
    """The client settings that scope publication could not be read."""


def excluded_planets(workspace):
    """Client planet exclusions, read without importing solar-client at module load."""
    global _inventory
    if _inventory is None:
        if not INVENTORY.is_file():
            raise PublicationUnavailable('Client skill inventory is unavailable')
        try:
            spec = importlib.util.spec_from_file_location('skill_inventory', INVENTORY)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # ImportError, SyntaxError, AttributeError, ...
            raise PublicationUnavailable('Client skill inventory could not be loaded') from exc
        _inventory = module
    try:
        return set(_inventory.settings(workspace).get('sync_exclude_planets', []))
    except ValueError as exc:
        raise PublicationUnavailable(str(exc))


def bounded_read(path, limit):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Published file exceeds size limit')
    return data


def operations_root(planet):
    """The planet's operations/ directory, refusing one that escapes the planet."""
    root = planet.resolve()
    operations = (planet / OPERATIONS).resolve()
    if not operations.is_relative_to(root):
        raise ValueError('Planet operations directory escapes the planet')
    return root, operations


def confined(planet, relative, suffixes):
    if not isinstance(relative, str):
        raise ValueError('Invalid published path')
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != OPERATIONS:
        raise ValueError('Published path must stay inside planet operations')
    root, operations = operations_root(planet)
    target = (planet / rel).resolve(strict=True)
    if (not target.is_relative_to(root) or not target.is_relative_to(operations)
            or target.suffix.lower() not in suffixes or not target.is_file()):
        raise ValueError('Published path escapes its allowed scope')
    return target


def read_index(planet):
    """Validated index for one planet, or None when it publishes nothing."""
    index = planet / INDEX_RELATIVE
    if not index.is_file():
        return None
    root, operations = operations_root(planet)
    resolved = index.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_relative_to(operations):
        raise ValueError('Report index escapes operations')
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
    return dict(reports=validated, evidence=evidence)


def published_planets(workspace):
    workspace = Path(workspace).resolve()
    excluded = excluded_planets(workspace)
    for planet in sorted((workspace / 'planets').glob('*')):
        if planet.name in excluded or not NAME.fullmatch(planet.name):
            continue
        if not planet.is_dir() or not planet.resolve().is_relative_to(workspace / 'planets'):
            continue
        yield planet


def manifests(workspace):
    for planet in published_planets(workspace):
        try:
            data = read_index(planet)
        except (OSError, ValueError, TypeError):
            yield planet, None, INVALID_INDEX
            continue
        if data is not None:
            yield planet, data, None


def dashboard_url(value):
    """Accept only explicit loopback HTTP root URLs; never probe the tool."""
    if not isinstance(value, str) or not re.fullmatch(
            r'http://(?:127\.0\.0\.1|localhost):[0-9]{1,5}/', value):
        raise ValueError('Dashboard URL must be a loopback HTTP root with a port')
    if not 1 <= urlsplit(value).port <= 65535:
        raise ValueError('Invalid dashboard port')
    return value


def read_dashboards(planet):
    index = planet / DASHBOARDS_RELATIVE
    if not index.is_file():
        return []
    index = confined(planet, DASHBOARDS_RELATIVE, {'.json'})
    data = json.loads(bounded_read(index, MAX_INDEX))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported dashboard index')
    rows = data.get('dashboards')
    if not isinstance(rows, list) or len(rows) > 30:
        raise ValueError('Invalid dashboard index limits')
    validated = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid dashboard entry')
        keys = ('title', 'description', 'owner', 'updated_at', 'start_command')
        if any(not isinstance(row.get(key), str) or not row[key].strip()
               or len(row[key]) > 2000 for key in keys):
            raise ValueError('Invalid dashboard metadata')
        if row.get('mode') not in {'read_only', 'interactive'}:
            raise ValueError('Invalid dashboard mode')
        validated.append({**{key: row[key] for key in keys},
                          'mode': row['mode'],
                          'href': dashboard_url(row.get('url')), 'kind': 'tool'})
    return validated


def dashboard_index(workspace):
    """Group existing reports and independent tool links without probing them."""
    reports = report_index(workspace)
    items = [{**row, 'kind': 'report', 'mode': 'read_only'} for row in reports['reports']]
    errors = [{**error, 'source': 'reports'} for error in reports['errors']]
    for planet in published_planets(workspace):
        try:
            rows = read_dashboards(planet)
        except (OSError, ValueError, TypeError):
            errors.append({'planet': planet.name, 'source': 'dashboards', 'error': INVALID_INDEX})
            continue
        items.extend({**row, 'planet': planet.name} for row in rows)
    return {'dashboards': items, 'errors': errors}


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
    workspace = Path(workspace).resolve()
    if name in excluded_planets(workspace):
        raise ValueError('Report is not available')
    planet = workspace / 'planets' / name
    if not planet.is_dir() or not planet.resolve().is_relative_to(workspace / 'planets'):
        raise ValueError('Report is not available')
    try:
        data = read_index(planet)
    except (OSError, ValueError, TypeError):
        raise ValueError('Report is not available')
    if data is None:
        raise ValueError('Report is not available')
    html_paths = {row['path'] for row in data['reports']}
    if relative not in html_paths and relative not in data['evidence']:
        raise ValueError('File is not explicitly published')
    target = confined(planet, relative, {'.html'} if relative in html_paths else {'.md', '.txt'})
    return bounded_read(target, MAX_REPORT), ('text/html' if relative in html_paths else 'text/plain') + '; charset=utf-8'
