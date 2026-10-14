"""Read-only view of the tools planets declare and this machine registers.

Two independent sources, joined here and never merged on disk:

* **Declaration** — `planets/<planet>/.solar/dashboards.json`, owned and
  versioned by the planet. It says *what* a surface is and *where it answers*.
* **Registration** — the `dashboards` block in `.solar/settings.json`, owned by
  Solar Client on this machine. It says *which* surfaces are active here and
  *how* to start them (a start command is machine-specific: it carries paths).

The console shows the intersection. It never starts, probes or mutates a tool;
`start_command` is copyable text. Starting a registered surface is an explicit
operator action: copy the command and run it.
"""
from datetime import datetime
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

from operation_publication import (INVALID_INDEX, MAX_INDEX, NAME, bounded_read,
                                    excluded_planets, published_planets)
from operation_publication import PublicationUnavailable  # re-exported for the route

# The planet's own `.solar/`, not the workspace one. It mirrors the tool-config
# convention (a repo-owned dot-directory, like `.claude`): the planet declares
# its surfaces next to itself. The workspace `.solar/` stays Client-managed and
# is never read as a declaration source.
DASHBOARDS_RELATIVE = '.solar/dashboards.json'
SETTINGS_RELATIVE = '.solar/settings.json'
MAX_SURFACES = 30
# A surface `name` is a single URL-safe segment with **no dots**: `.` and `..`
# can never be a name, and the name is the stable identity, unique per planet and
# independent of the file or url it points at. Changing the target keeps the id.
ID = re.compile(r'[A-Za-z0-9_-]+\Z')
SURFACE_ID = re.compile(r'[A-Za-z0-9_.-]+:[A-Za-z0-9_-]+\Z')
MODES = {'read_only', 'interactive'}
MAX_TEXT = 2000
MAX_COMMAND = 4000
# A surface is either a *tool* (a loopback HTTP root) or a *file* (an HTML page
# the planet generates). Exactly one of `url`/`file` is declared, never both.
ENTRY_KEYS = {'name', 'title', 'description', 'owner', 'updated_at',
              'url', 'file', 'mode'}
FILE_ROOT = 'operations'
FILE_SUFFIXES = {'.html'}
MAX_FILE = 4 * 1024 * 1024
FILE_MIME = 'text/html; charset=utf-8'


def declaration(planet):
    """Resolve a planet's declaration, refusing anything that leaves the planet.

    The file does not live under `operations/`, so it gets its own confinement:
    the resolved path must stay inside the planet, be a regular `.json` file
    reached without a symlink hop, and the `.solar` entry itself must not be a
    link.
    """
    root = planet.resolve()
    solar = planet / '.solar'
    if solar.is_symlink():
        raise ValueError('Planet .solar must not be a symlink')
    target = solar / 'dashboards.json'
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise ValueError('Unreadable dashboard declaration') from exc
    if (not resolved.is_relative_to(root) or not resolved.is_relative_to(solar.resolve())
            or resolved.suffix.lower() != '.json' or not resolved.is_file()
            or not target.is_file()):
        raise ValueError('Dashboard declaration escapes its planet')
    return resolved


def dashboard_url(value):
    """Accept only explicit loopback HTTP root URLs; never probe the tool.

    The port is `[1-9][0-9]{0,4}`: a leading zero (e.g. `:080`) is refused, and the
    numeric range is checked as well.
    """
    if not isinstance(value, str) or not re.fullmatch(
            r'http://(?:127\.0\.0\.1|localhost):[1-9][0-9]{0,4}/', value):
        raise ValueError('Dashboard URL must be a loopback HTTP root with a port')
    port = int(value.rsplit(':', 1)[1][:-1])
    if not 1 <= port <= 65535:
        raise ValueError('Invalid dashboard port')
    return value


def _bounded_text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError(f'Invalid dashboard {field}')
    return value


def dashboard_file(value):
    """Accept an HTML page inside the planet's `operations/`, never outside it.

    The path is validated here only for *shape*; the file is resolved inside the
    planet when the console serves it, so a bad declaration never leaks a path
    and a moved file simply fails to open.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError('Invalid dashboard file')
    rel = Path(value)
    if (rel.is_absolute() or '..' in rel.parts or not rel.parts
            or rel.parts[0] != FILE_ROOT or rel.suffix.lower() not in FILE_SUFFIXES):
        raise ValueError('Dashboard file must be an HTML page inside operations/')
    return value


def _dashboard_source(row):
    """Exactly one of `url` (loopback tool) or `file` (published page)."""
    url, file = row.get('url'), row.get('file')
    if (url is None) == (file is None):
        raise ValueError('A dashboard declares exactly one of url or file')
    if url is not None:
        return 'tool', dashboard_url(url)
    return 'file', dashboard_file(file)


def _surface_href(planet, name, kind, value):
    """Tools link straight to loopback; files are served by the console itself.

    A file's href is built from the planet and the entry name, never from the
    declared path: the route re-resolves the path from the declaration, so a
    request can never name a file that was not declared.
    """
    if kind == 'tool':
        return value
    return f'/dashboards/{quote(planet, safe="")}/{quote(name, safe="")}'


def read_declared(planet):
    """Validated declarations for one planet.

    Returns `(declared, errors)`. A single bad entry never hides the valid ones
    of the same planet: it is reported with its own id and the rest still list.
    A structurally broken file (bad JSON, wrong version, too many entries) is the
    only case that reports the whole planet.
    """
    index = planet / DASHBOARDS_RELATIVE
    if not index.is_file():
        return [], []
    target = declaration(planet)
    data = json.loads(bounded_read(target, MAX_INDEX))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported dashboard declaration')
    rows = data.get('dashboards')
    if not isinstance(rows, list) or len(rows) > MAX_SURFACES:
        raise ValueError('Invalid dashboard declaration limits')
    declared, errors, seen = [], [], set()
    for position, row in enumerate(rows):
        try:
            entry = _validated_entry(planet, row, seen)
        except ValueError as exc:
            label = row.get('name') if isinstance(row, dict) and isinstance(row.get('name'), str) else f'#{position}'
            errors.append({'planet': planet.name, 'id': f'{planet.name}:{label}',
                           'source': 'dashboards', 'error': str(exc)})
            continue
        seen.add(entry['name'])
        declared.append(entry)
    return declared, errors


def _validated_entry(planet, row, seen):
    if not isinstance(row, dict):
        raise ValueError('Invalid dashboard entry')
    extra = set(row) - ENTRY_KEYS
    if extra:
        raise ValueError(f'Unknown key(s): {", ".join(sorted(extra))}')
    name = row.get('name')
    if not isinstance(name, str) or not ID.fullmatch(name):
        raise ValueError('Invalid dashboard name (single safe segment, no dots)')
    if name in seen:
        raise ValueError('Duplicate dashboard name')
    if row.get('mode') not in MODES:
        raise ValueError('Invalid dashboard mode')
    kind, value = _dashboard_source(row)
    if kind == 'file' and row['mode'] != 'read_only':
        raise ValueError('A file view is always read_only')
    return {
        'id': f'{planet.name}:{name}',
        'planet': planet.name,
        'kind': kind,
        'name': name,
        'title': _bounded_text(row.get('title'), 'title'),
        'description': _bounded_text(row.get('description'), 'description'),
        'owner': _bounded_text(row.get('owner'), 'owner'),
        'updated_at': _bounded_text(row.get('updated_at'), 'updated_at'),
        'href': _surface_href(planet.name, name, kind, value),
        'mode': row['mode'],
        'file': value if kind == 'file' else None,
    }


def _registration(workspace):
    """Client-side registration block; {} when absent or unreadable."""
    path = Path(workspace).resolve() / SETTINGS_RELATIVE
    if not path.is_file():
        return {'enabled': True, 'registered': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Workspace settings must be an object')
    block = data.get('dashboards')
    if block is None:
        return {'enabled': True, 'registered': {}}
    if not isinstance(block, dict):
        raise ValueError('dashboards must be an object')
    unknown = set(block) - {'enabled', 'registered'}
    if unknown:
        raise ValueError(f'unknown key(s) in dashboards: {", ".join(sorted(unknown))}')
    if 'enabled' in block and not isinstance(block['enabled'], bool):
        raise ValueError('dashboards.enabled must be a boolean')
    rows = block.get('registered', [])
    if not isinstance(rows, list) or len(rows) > MAX_SURFACES * 4:
        raise ValueError('dashboards.registered must be a bounded array')
    registered = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid dashboards.registered entry')
        if set(row) - {'id', 'start_command'}:
            raise ValueError('Unknown key in dashboards.registered entry')
        surface = row.get('id')
        if not isinstance(surface, str) or not SURFACE_ID.fullmatch(surface):
            raise ValueError('Invalid registered dashboard id')
        command = row.get('start_command')
        if command is not None:
            if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND:
                raise ValueError('Invalid registered start command')
        registered[surface] = command
    return {'enabled': block.get('enabled', True), 'registered': registered}


def dashboard_index(workspace):
    """Declared surfaces joined with this machine's registration.

    Three registration states are distinguished for a tool: declared with no
    command, a command with no declaration, and both. A view (`file`) is shown as
    soon as it is declared and never needs registration.
    """
    items, errors = [], []
    try:
        registration = _registration(workspace)
    except (OSError, ValueError, TypeError):
        return {'dashboards': items,
                'errors': [{'planet': '', 'id': '', 'source': 'registration', 'error': INVALID_INDEX}]}
    if not registration['enabled']:
        return {'dashboards': items, 'errors': errors}
    registered = registration['registered']
    declared_ids = set()
    for planet in published_planets(workspace):
        try:
            declared, entry_errors = read_declared(planet)
        except (OSError, ValueError, TypeError):
            errors.append({'planet': planet.name, 'id': '', 'source': 'dashboards', 'error': INVALID_INDEX})
            continue
        errors.extend(entry_errors)
        for row in declared:
            declared_ids.add(row['id'])
            command = registered.get(row['id'])
            items.append({**row,
                          'registered': row['id'] in registered,
                          'start_command': command,
                          'freshness': _freshness(planet, row)})
    # A registered id with no matching declaration is a stale registration: it is
    # surfaced rather than silently dropped. Views never appear here.
    for surface in sorted(registered):
        if surface not in declared_ids:
            errors.append({'planet': surface.split(':', 1)[0], 'id': surface,
                           'source': 'registration', 'error': 'registered_dashboard_not_declared'})
    return {'dashboards': items, 'errors': errors}


def _freshness(planet, row):
    """Filesystem freshness for a `file` view: the file's own mtime, not the HTML.

    With a stable name a view is always "the latest". The mtime says when the file
    was written here; it does not prove the underlying data is fresh, which the
    view and its owner must still state.
    """
    if row['kind'] != 'file':
        return None
    try:
        target = _declared_file(planet, row['name'])
        stamp = datetime.fromtimestamp(target.stat().st_mtime).astimezone()
    except (OSError, ValueError, TypeError):
        return None
    return stamp.isoformat(timespec='seconds')


def _declared_file(planet, name):
    """The one declared HTML page for `name`, confined to the planet's operations/.

    Re-validates the declaration and re-resolves the file, so a request can only
    reach a page that is declared today. Refuses a symlink hop, a path that leaves
    `operations/`, an uppercase suffix and anything over the size cap.
    """
    declared, _ = read_declared(planet)
    relative = next((row['file'] for row in declared
                     if row['name'] == name and row['kind'] == 'file'), None)
    if relative is None:
        raise ValueError('File is not a declared dashboard')
    root = planet.resolve()
    operations = (planet / FILE_ROOT).resolve()
    if not operations.is_relative_to(root):
        raise ValueError('File is not a declared dashboard')
    target = planet / relative
    if target.is_symlink():
        raise ValueError('File is not a declared dashboard')
    resolved = target.resolve(strict=True)
    if (not resolved.is_relative_to(root) or not resolved.is_relative_to(operations)
            or resolved.suffix not in FILE_SUFFIXES or not resolved.is_file()):
        raise ValueError('File is not a declared dashboard')
    if resolved.stat().st_size > MAX_FILE:
        raise ValueError('Published file exceeds size limit')
    return resolved


def published_dashboard_file(workspace, request_path):
    """Serve a declared `file` dashboard for `<planet>:<name>`, read only.

    The route never carries a filesystem path: the planet and the entry name are
    looked up again against the declaration, so nothing outside an explicitly
    declared HTML page can be read.
    """
    path = unquote(request_path)
    parts = path.split('/', 3)
    if len(parts) != 4 or parts[:2] != ['', 'dashboards'] or not NAME.fullmatch(parts[2]):
        raise ValueError('Invalid dashboard request')
    planet_name, name = parts[2], parts[3]
    workspace = Path(workspace).resolve()
    if planet_name in excluded_planets(workspace) or not ID.fullmatch(name):
        raise ValueError('Dashboard is not available')
    planet = workspace / 'planets' / planet_name
    if not planet.is_dir() or not planet.resolve().is_relative_to(workspace / 'planets'):
        raise ValueError('Dashboard is not available')
    try:
        target = _declared_file(planet, name)
    except (OSError, ValueError, TypeError):
        raise ValueError('Dashboard is not available')
    return bounded_read(target, MAX_FILE), FILE_MIME
