"""Dashboards: planet declarations joined with this machine's registration.

The console reads both sources and stays read only. These tests use a synthetic
workspace; no real planet, real settings or real tool is opened or started.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[3] / 'skills/solar-app/scripts'
sys.path.insert(0, str(SCRIPTS))
import app_http
import operation_dashboards
import operation_publication


class DashboardWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.planet = self.workspace / 'planets/example'
        self.planet.mkdir(parents=True)

    def declare(self, **overrides):
        entry = dict(name='triage', title='Triage', description='Review contacts',
                     owner='Sales', updated_at='2026-10-13',
                     url='http://127.0.0.1:8777/', mode='interactive')
        entry.update(overrides)
        path = self.planet / operation_dashboards.DASHBOARDS_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(version=1, dashboards=[entry])))
        return path

    def register(self, rows, enabled=None):
        block = {'registered': rows}
        if enabled is not None:
            block['enabled'] = enabled
        settings = self.workspace / operation_dashboards.SETTINGS_RELATIVE
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({'layout': 'solar-client-v1.2', 'dashboards': block}))

    def declare_file(self, relative='operations/leadership/reports/daily.html',
                     body='<!doctype html><title>Daily</title>', **overrides):
        entry = dict(name='attention', title='Attention', description='Daily view',
                     owner='CEO', updated_at='2026-10-13', url=None,
                     file=relative, mode='read_only')
        entry.update(overrides)
        path = self.planet / operation_dashboards.DASHBOARDS_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(version=1, dashboards=[entry])))
        target = self.planet / relative
        # Only materialise the file when the path really stays inside the planet.
        if relative and not Path(relative).is_absolute() and '..' not in Path(relative).parts:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        return target

    def by_id(self, data):
        return {row['id']: row for row in data['dashboards'] if row.get('id')}


class Declarations(DashboardWorkspace):
    def test_declaration_without_registration_is_reported_as_such(self):
        self.declare()
        rows = operation_dashboards.dashboard_index(self.workspace)['dashboards']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'tool')
        self.assertFalse(rows[0]['registered'])
        self.assertIsNone(rows[0]['start_command'])
        self.assertEqual(rows[0]['id'], 'example:triage')

    def test_registration_supplies_the_start_command(self):
        self.declare()
        self.register([{'id': 'example:triage', 'start_command': 'python3 server.py'}])
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:triage']
        self.assertTrue(row['registered'])
        self.assertEqual(row['start_command'], 'python3 server.py')

    def test_registration_without_a_command_is_still_registered(self):
        self.declare()
        self.register([{'id': 'example:triage', 'start_command': None}])
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:triage']
        self.assertTrue(row['registered'])
        self.assertIsNone(row['start_command'])

    def test_registration_never_overrides_the_declared_url_or_mode(self):
        self.declare()
        self.register([{'id': 'example:triage', 'start_command': 'x'}])
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:triage']
        self.assertEqual(row['href'], 'http://127.0.0.1:8777/')
        self.assertEqual(row['mode'], 'interactive')

    def test_every_item_is_a_tool_and_report_is_not_a_kind(self):
        # The report concept is retired: the console never surfaces a `report`.
        self.declare()
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual([row['kind'] for row in data['dashboards']], ['tool'])
        self.assertNotIn('report', {row['kind'] for row in data['dashboards']})

    def test_disabled_block_hides_every_declared_tool(self):
        self.declare()
        self.register([{'id': 'example:triage', 'start_command': 'x'}], enabled=False)
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual(data['dashboards'], [])
        self.assertEqual(data['errors'], [])

    def test_absent_block_still_lists_declared_tools_without_touching_settings(self):
        self.declare()
        settings = self.workspace / operation_dashboards.SETTINGS_RELATIVE
        rows = operation_dashboards.dashboard_index(self.workspace)['dashboards']
        self.assertEqual([r['kind'] for r in rows], ['tool'])
        self.assertFalse(rows[0]['registered'])
        self.assertFalse(settings.exists())

    def test_a_broken_registration_is_reported_and_still_lists_declared_tools(self):
        # The reader can no longer join the registration, so it reports the error
        # and degrades to "registered: false" instead of hiding every dashboard.
        self.declare()
        settings = self.workspace / operation_dashboards.SETTINGS_RELATIVE
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({'dashboards': {'registered': [{'id': 'bad'}]}}))
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual([row['id'] for row in data['dashboards']], ['example:triage'])
        self.assertFalse(data['dashboards'][0]['registered'])
        self.assertEqual(data['errors'][0]['source'], 'registration')

    def test_a_broken_registration_still_lists_the_views(self):
        # A view needs no registration, so a malformed block must not hide it. The
        # registration error is kept and the view is still published.
        self.declare_file()
        settings = self.workspace / operation_dashboards.SETTINGS_RELATIVE
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({'dashboards': {'registered': [{'id': 'bad'}]}}))
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual([row['id'] for row in data['dashboards']], ['example:attention'])
        self.assertIn('registration', {error['source'] for error in data['errors']})

    def test_a_non_string_mode_isolates_the_entry(self):
        # `mode: []`/{} used to raise TypeError and discard the whole planet,
        # valid entries included. The bad one is isolated, the good one lists.
        path = self.declare()
        data = json.loads(path.read_text())
        data['dashboards'].append(dict(name='broken', title='B', description='D', owner='O',
                                       updated_at='U', url='http://127.0.0.1:1/', mode=[]))
        path.write_text(json.dumps(data))
        result = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual([row['id'] for row in result['dashboards']], ['example:triage'])
        self.assertEqual([error['id'] for error in result['errors']], ['example:broken'])

    def test_registration_is_read_from_the_legacy_manifest(self):
        # An unmigrated workspace keeps registration in manifest.json; the console
        # must resolve the same file the CLI does, or the two disagree.
        self.declare()
        manifest = self.workspace / '.solar/manifest.json'
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({'dashboards': {'registered': [
            {'id': 'example:triage', 'start_command': 'run.sh'}]}}))
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:triage']
        self.assertTrue(row['registered'])
        self.assertEqual(row['start_command'], 'run.sh')

    def test_settings_win_over_the_legacy_manifest(self):
        self.declare()
        manifest = self.workspace / '.solar/manifest.json'
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({'dashboards': {'registered': [
            {'id': 'example:triage', 'start_command': 'legacy.sh'}]}}))
        self.register([{'id': 'example:triage', 'start_command': 'current.sh'}])
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:triage']
        self.assertEqual(row['start_command'], 'current.sh')

    def test_a_bad_entry_is_isolated_and_reported(self):
        # One invalid entry no longer discards the whole planet: the good one
        # still lists and the bad one is reported with its own id.
        path = self.declare()
        data = json.loads(path.read_text())
        data['dashboards'].append(dict(name='broken', title='', description='D', owner='O',
                                       updated_at='U', url='http://127.0.0.1:1/', mode='read_only'))
        path.write_text(json.dumps(data))
        result = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual([row['id'] for row in result['dashboards']], ['example:triage'])
        self.assertEqual([error['id'] for error in result['errors']], ['example:broken'])

    def test_a_structurally_broken_declaration_reports_the_whole_planet(self):
        path = self.declare()
        path.write_text(json.dumps(dict(version=2, dashboards=[])))
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual(data['dashboards'], [])
        self.assertEqual(data['errors'][0]['source'], 'dashboards')

    def test_the_declared_path_never_appears_in_the_href(self):
        self.declare_file()
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:attention']
        self.assertEqual(row['href'], '/dashboards/example/attention')
        self.assertNotIn('operations', row['href'])
        self.assertNotIn('daily.html', row['href'])
        # `file` stays on the item for freshness, but never in the link.
        self.assertEqual(row['file'], 'operations/leadership/reports/daily.html')

    def test_a_registered_id_without_a_declaration_is_surfaced(self):
        self.declare()
        self.register([{'id': 'example:ghost', 'start_command': 'x'}])
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertIn({'planet': 'example', 'id': 'example:ghost', 'source': 'registration',
                       'error': 'registered_dashboard_not_declared'}, data['errors'])

    def test_a_view_reports_the_file_mtime_as_freshness(self):
        self.declare_file()
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:attention']
        self.assertIsNotNone(row['freshness'])
        # A tool has no filesystem freshness.
        self.assertIsNone(operation_dashboards._freshness(self.planet, dict(kind='tool', name='x')))

    def test_a_view_with_a_date_stamped_or_dotted_name_is_refused(self):
        for bad in ('daily.html', 'a.b', '..', 'attention/2026'):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                operation_dashboards._validated_entry(self.planet, dict(
                    name=bad, title='T', description='D', owner='O', updated_at='U',
                    file='operations/leadership/reports/daily.html', mode='read_only'), set())

    def test_a_view_must_be_read_only(self):
        with self.assertRaises(ValueError):
            operation_dashboards._validated_entry(self.planet, dict(
                name='attention', title='T', description='D', owner='O', updated_at='U',
                file='operations/leadership/reports/daily.html', mode='interactive'), set())

    def test_a_bad_declaration_does_not_hide_a_valid_one(self):
        self.declare()
        (self.workspace / 'planets/other').mkdir(parents=True)
        broken = self.workspace / 'planets/other/.solar/dashboards.json'
        broken.parent.mkdir(parents=True)
        broken.write_text(json.dumps(dict(version=1, dashboards=[dict(
            name='x', title='', description='D', owner='O', updated_at='U',
            url='http://127.0.0.1:1/', mode='read_only')])))
        data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual([row['planet'] for row in data['dashboards']], ['example'])
        self.assertEqual([error['planet'] for error in data['errors']], ['other'])

    def test_declaration_and_settings_are_never_written(self):
        path = self.declare()
        self.register([{'id': 'example:triage', 'start_command': 'x'}])
        settings = self.workspace / operation_dashboards.SETTINGS_RELATIVE
        before = (path.read_bytes(), settings.read_bytes())
        operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual(before, (path.read_bytes(), settings.read_bytes()))

    def test_excluded_planet_is_not_opened(self):
        self.declare()
        with patch.object(operation_publication, 'excluded_planets', return_value={'example'}), \
             patch.object(operation_dashboards, 'read_declared',
                          side_effect=AssertionError('must not read')):
            data = operation_dashboards.dashboard_index(self.workspace)
        self.assertEqual(data['dashboards'], [])


class FileSurfaces(DashboardWorkspace):
    """A `file` entry is a generated view the console serves itself, read only."""

    def test_a_file_entry_is_a_view_with_an_internal_href(self):
        self.declare_file()
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:attention']
        self.assertEqual(row['kind'], 'file')
        self.assertEqual(row['href'], '/dashboards/example/attention')
        self.assertFalse(row['registered'])
        self.assertIsNone(row['start_command'])

    def test_an_entry_needs_exactly_one_of_url_or_file(self):
        self.declare_file()
        path = self.planet / operation_dashboards.DASHBOARDS_RELATIVE
        both = dict(name='attention', title='T', description='D', owner='O',
                    updated_at='U', url='http://127.0.0.1:1/',
                    file='operations/leadership/reports/daily.html', mode='read_only')
        path.write_text(json.dumps(dict(version=1, dashboards=[both])))
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])
        neither = dict(name='attention', title='T', description='D', owner='O',
                       updated_at='U', mode='read_only')
        path.write_text(json.dumps(dict(version=1, dashboards=[neither])))
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_a_file_outside_operations_is_refused(self):
        for relative in ('private/notes.html', '/etc/notes.html',
                         'operations/../escape.html', 'operations/notes.txt'):
            with self.subTest(relative=relative):
                self.declare_file(relative=relative)
                self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_an_uppercase_html_suffix_is_refused(self):
        # `.HTML` used to pass `.lower()` here, list as valid, then 404 on open.
        # The suffix must be exactly `.html`, as `seed` already enforces.
        self.declare_file(relative='operations/leadership/reports/daily.HTML')
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])
        with self.assertRaises(ValueError):
            operation_dashboards.dashboard_file('operations/leadership/reports/daily.HTML')

    def test_the_route_serves_only_a_declared_file(self):
        target = self.declare_file(body='<p>view</p>')
        body, mime = operation_dashboards.published_dashboard_file(
            self.workspace, '/dashboards/example/attention')
        self.assertEqual(body, b'<p>view</p>')
        self.assertTrue(mime.startswith('text/html'))
        # A name that was not declared is refused, and so is any path the route
        # does not carry.
        for path in ('/dashboards/example/other',
                     '/dashboards/example/../private/notes.html',
                     '/dashboards/example/operations/leadership/reports/daily.html',
                     '/dashboards/example/%2e%2e/private/notes.html',
                     '/dashboards/ghost/attention', '/dashboards/example/'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                operation_dashboards.published_dashboard_file(self.workspace, path)
        self.assertTrue(target.is_file())

    def test_a_declared_file_that_escapes_via_symlink_is_refused(self):
        self.declare_file()
        outside = self.workspace / 'outside.html'
        outside.write_text('secret')
        target = self.planet / 'operations/leadership/reports/daily.html'
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            operation_dashboards.published_dashboard_file(self.workspace, '/dashboards/example/attention')

    def test_an_excluded_planet_file_is_not_served(self):
        self.declare_file()
        with patch.object(operation_dashboards, 'excluded_planets', return_value={'example'}):
            with self.assertRaises(ValueError):
                operation_dashboards.published_dashboard_file(self.workspace, '/dashboards/example/attention')


class DeclarationValidation(DashboardWorkspace):
    def bad(self, **overrides):
        self.declare(**overrides)
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_required_fields(self):
        for field in ('title', 'description', 'owner', 'updated_at'):
            with self.subTest(field=field):
                self.bad(**{field: ''})
                self.bad(**{field: None})

    def test_mode_is_required_and_bounded(self):
        self.bad(mode='readwrite')
        self.bad(mode=None)

    def test_name_must_be_a_bounded_id_and_unique(self):
        self.bad(name='with space')
        self.bad(name='')
        path = self.planet / operation_dashboards.DASHBOARDS_RELATIVE
        entry = dict(name='triage', title='T', description='D', owner='O',
                     updated_at='U', url='http://127.0.0.1:1/', mode='read_only')
        path.write_text(json.dumps(dict(version=1, dashboards=[entry, entry])))
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_limits_and_version(self):
        path = self.planet / operation_dashboards.DASHBOARDS_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(name='triage', title='T', description='D', owner='O',
                     updated_at='U', url='http://127.0.0.1:1/', mode='read_only')
        path.write_text(json.dumps(dict(version=2, dashboards=[entry])))
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])
        path.write_text(json.dumps(dict(version=1, dashboards=[entry] * 31)))
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_symlinked_declaration_inside_the_planet_is_refused(self):
        path = self.declare()
        outside = self.planet / 'private/notes.json'
        outside.parent.mkdir(parents=True)
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_the_declaration_lives_in_the_planet_solar_directory(self):
        path = self.declare()
        self.assertEqual(path, self.planet / '.solar/dashboards.json')
        self.assertNotIn('operations', path.parts)
        row = self.by_id(operation_dashboards.dashboard_index(self.workspace))['example:triage']
        self.assertEqual(row['kind'], 'tool')

    def test_symlinked_declaration_leaving_the_planet_is_refused(self):
        path = self.declare()
        outside = self.workspace / 'outside.json'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])

    def test_symlinked_planet_solar_directory_is_refused(self):
        outside = self.workspace / 'elsewhere'
        outside.mkdir()
        (outside / 'dashboards.json').write_text(json.dumps(dict(
            version=1, dashboards=[dict(name='triage', title='T', description='D',
                                        owner='O', updated_at='U',
                                        url='http://127.0.0.1:8777/', mode='read_only')])))
        (self.planet / '.solar').symlink_to(outside)
        self.assertTrue(operation_dashboards.dashboard_index(self.workspace)['errors'])


class UrlAllowlist(unittest.TestCase):
    def test_accepts_loopback_http_roots(self):
        for url in ['http://localhost:1/', 'http://127.0.0.1:65535/']:
            self.assertEqual(operation_dashboards.dashboard_url(url), url)

    def test_refuses_everything_else(self):
        for url in ['https://localhost:8777/', 'https://example.com/', 'http://localhost/',
                    'http://localhost:0/', 'http://localhost:080/', 'http://127.0.0.1:00/',
                    'http://localhost:65536/', 'http://[::1]:8777/',
                    'http://localhost:8777/path', 'http://localhost:8777/?x=1',
                    'http://localhost:8777/#x', 'http://user@localhost:8777/',
                    'http://localhost.evil:8777/', 'http://127.1:8777/', 'file:///tmp/x',
                    'javascript:alert(1)', 'http://localhost:8777/\n', '', None, 7]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                operation_dashboards.dashboard_url(url)


class PublicationModule(unittest.TestCase):
    """The neutral module that survived the report retirement."""

    def test_publication_module_exposes_only_neutral_names(self):
        # No report or dashboard logic may creep back into this shared module.
        import types
        public = {name for name in dir(operation_publication)
                  if not name.startswith('_')
                  and not isinstance(getattr(operation_publication, name), types.ModuleType)
                  and name not in {'Path'}}
        self.assertEqual(public, {
            'CLIENT', 'INVENTORY', 'MAX_INDEX', 'INVALID_INDEX', 'NAME',
            'PublicationUnavailable', 'excluded_planets', 'bounded_read',
            'published_planets',
        })

    def test_bounded_read_refuses_a_file_over_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'big.json'
            path.write_bytes(b'x' * 11)
            self.assertEqual(operation_publication.bounded_read(path, 11), b'x' * 11)
            with self.assertRaises(ValueError):
                operation_publication.bounded_read(path, 10)

    def test_published_planets_skips_excluded_and_odd_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            for name in ('good', 'excluded', 'with space'):
                (workspace / 'planets' / name).mkdir(parents=True)
            (workspace / 'planets' / 'a_file').write_text('not a dir')
            with patch.object(operation_publication, 'excluded_planets', return_value={'excluded'}):
                names = [p.name for p in operation_publication.published_planets(workspace)]
            self.assertEqual(names, ['good'])


class Route(DashboardWorkspace):
    def test_a_declared_view_is_served_by_the_route_with_csp(self):
        self.declare_file(body='<p>view</p>')
        seen = {}

        class Handler:
            wfile = None

            def send_response(self, status):
                seen['status'] = status

            def send_header(self, key, value):
                seen.setdefault('headers', {})[key] = value

            def end_headers(self):
                pass

            def _send_json(self, payload, status=200):
                seen['payload'], seen['status'] = payload, status

        class Sink:
            def __init__(self):
                self.buf = b''

            def write(self, data):
                self.buf += data

        handler = Handler()
        handler.wfile = Sink()
        app_http.get(handler, '/dashboards/example/attention', {}, self.workspace)
        self.assertEqual(seen['status'], 200)
        self.assertEqual(handler.wfile.buf, b'<p>view</p>')
        self.assertEqual(seen['headers']['Content-Security-Policy'],
                         "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox")
        self.assertNotIn('allow-scripts', seen['headers']['Content-Security-Policy'])
        self.assertNotIn('allow-same-origin', seen['headers']['Content-Security-Policy'])
        self.assertEqual(seen['headers']['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(seen['headers']['Referrer-Policy'], 'no-referrer')
        self.assertEqual(seen['headers']['Cache-Control'], 'no-store')

    def test_route_joins_both_sources_and_is_read_only(self):
        self.declare()
        self.register([{'id': 'example:triage', 'start_command': 'python3 server.py'}])
        seen = {}

        class Handler:
            def _send_json(self, payload, status=200):
                seen['payload'], seen['status'] = payload, status

        app_http.get(Handler(), '/api/console/dashboards', {}, self.workspace)
        self.assertEqual([row['kind'] for row in seen['payload']['dashboards']], ['tool'])
        self.assertEqual(seen['status'], 200)

    def test_the_retired_routes_answer_404(self):
        for path in ('/api/console/reports', '/reports/example/operations/attention.html'):
            with self.subTest(path=path):
                seen = {}

                class Handler:
                    def _send_json(self, payload, status=200):
                        seen['payload'], seen['status'] = payload, status

                app_http.get(Handler(), path, {}, self.workspace)
                self.assertEqual(seen['status'], 404, path)


if __name__ == '__main__':
    unittest.main()
