"""Publication confines report files; it never turns the console into a file server."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[3] / 'skills/solar-app/scripts'
sys.path.insert(0, str(SCRIPTS))
import operation_reports
import app_http


class PublishedReports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.planet = self.workspace / 'planets/example'
        self.index = self.planet / 'operations/leadership/reports/index.json'
        self.index.parent.mkdir(parents=True)
        self.html = self.index.parent / 'attention.html'
        self.html.write_text('<script>shouldNotRun()</script><h1>Report</h1>')
        self.row = dict(path='operations/leadership/reports/attention.html', title='Attention', owner='Example', generated_at='2026-10-11', period='Today', coverage='Partial', next_decision='Review')
        self.publish()

    def publish(self):
        self.index.write_text(json.dumps(dict(version=1, reports=[self.row], evidence=[])))

    def test_explicit_publication_and_closed_file_scope(self):
        result = operation_reports.report_index(self.workspace)
        self.assertEqual(len(result['reports']), 1)
        body, mime = operation_reports.published_file(self.workspace, result['reports'][0]['href'])
        self.assertIn(b'Report', body)
        self.assertTrue(mime.startswith('text/html'))
        private = self.planet / 'operations/private.md'
        private.write_text('not published')
        for path in ('/reports/example/operations/private.md', '/reports/example/../private.md', '/reports/example/%2e%2e/private.md'):
            with self.assertRaises(ValueError):
                operation_reports.published_file(self.workspace, path)

    def test_symlink_escape_and_excluded_planets(self):
        outside = self.workspace / 'private.html'
        outside.write_text('private')
        self.html.unlink()
        self.html.symlink_to(outside)
        self.assertTrue(operation_reports.report_index(self.workspace)['errors'])
        settings = self.workspace / '.solar/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'sync_exclude_planets': ['example']}))
        result = operation_reports.report_index(self.workspace)
        self.assertEqual(result, dict(reports=[], errors=[]))

    def test_symlink_inside_the_planet_but_outside_operations_is_refused(self):
        # A file outside operations/ (notes with client data) must not be reachable
        # even when it lives in the same planet and carries the right suffix.
        private = self.planet / 'private/notes.html'
        private.parent.mkdir(parents=True)
        private.write_text('client data')
        link = self.planet / 'operations/leadership/reports/notes.html'
        link.symlink_to(private)
        # Declared as a report, with a valid .html suffix; only the confinement
        # check can reject it.
        self.row = dict(self.row, path='operations/leadership/reports/notes.html')
        self.index.write_text(json.dumps(dict(version=1, reports=[self.row], evidence=[])))
        self.assertTrue(operation_reports.report_index(self.workspace)['errors'])
        with self.assertRaises(ValueError):
            operation_reports.published_file(self.workspace, '/reports/example/' + self.row['path'])

    def test_symlinked_evidence_outside_operations_is_refused(self):
        private = self.planet / 'private/notes.txt'
        private.parent.mkdir(parents=True)
        private.write_text('client data')
        link = self.planet / 'operations/leadership/reports/notes.txt'
        link.symlink_to(private)
        # Listed as evidence, with a valid .txt suffix, so only the confinement
        # check can reject it.
        self.index.write_text(json.dumps(dict(version=1, reports=[self.row], evidence=['operations/leadership/reports/notes.txt'])))
        self.assertTrue(operation_reports.report_index(self.workspace)['errors'])
        with self.assertRaises(ValueError):
            operation_reports.published_file(self.workspace, '/reports/example/operations/leadership/reports/notes.txt')

    def test_operations_directory_that_escapes_the_planet_is_refused(self):
        # operations/ itself pointing outside the planet must not become a
        # trusted root that serves arbitrary files.
        planet = self.workspace / 'planets/escape'
        planet.mkdir(parents=True)
        outside = self.workspace / 'outside-operations'
        reports = outside / 'leadership/reports'
        reports.mkdir(parents=True)
        (reports / 'notes.html').write_text('client data')
        (reports / 'index.json').write_text(json.dumps(dict(version=1, reports=[dict(path='operations/leadership/reports/notes.html', title='Leak', owner='x', generated_at='2026-10-11', period='Today', coverage='Partial', next_decision='Review')], evidence=[])))
        (planet / 'operations').symlink_to(outside)
        self.assertTrue(operation_reports.report_index(self.workspace)['errors'])
        with self.assertRaises(ValueError):
            operation_reports.published_file(self.workspace, '/reports/escape/operations/leadership/reports/notes.html')

    def test_symlinked_report_is_a_404_not_a_file(self):
        class Handler:
            def __init__(self): self.headers = {}; self.wfile = io.BytesIO()
            def send_response(self, code): self.code = code
            def send_header(self, key, value): self.headers[key] = value
            def end_headers(self): pass
            def _send_json(self, payload, status=200): self.code, self.payload = status, payload
        private = self.planet / 'private/notes.html'
        private.parent.mkdir(parents=True)
        private.write_text('client data')
        link = self.planet / 'operations/leadership/reports/notes.html'
        link.symlink_to(private)
        # The link is listed in the index before it is requested, so the 404 can
        # only come from the confinement refusal, not from "not published".
        self.row = dict(self.row, path='operations/leadership/reports/notes.html')
        self.index.write_text(json.dumps(dict(version=1, reports=[self.row], evidence=[])))
        handler = Handler()
        app_http.get(handler, '/reports/example/' + self.row['path'], {}, self.workspace)
        self.assertEqual(handler.code, 404)

    def test_invalid_settings_refuse_discovery(self):
        settings = self.workspace / '.solar/settings.json'
        settings.parent.mkdir()
        settings.write_text('{broken')
        with self.assertRaises(ValueError):
            operation_reports.report_index(self.workspace)

    def test_served_html_disables_active_content(self):
        class Handler:
            def __init__(self): self.headers = {}; self.wfile = io.BytesIO()
            def send_response(self, code): self.code = code
            def send_header(self, key, value): self.headers[key] = value
            def end_headers(self): pass
        handler = Handler()
        app_http.get(handler, '/reports/example/' + self.row['path'], {}, self.workspace)
        self.assertEqual(handler.code, 200)
        self.assertIn("default-src 'none'", handler.headers['Content-Security-Policy'])
        self.assertIn('sandbox;', handler.headers['Content-Security-Policy'])
        self.assertNotIn('allow-scripts', handler.headers['Content-Security-Policy'])
        self.assertNotIn('allow-top-navigation', handler.headers['Content-Security-Policy'])
        self.assertNotIn('allow-popups', handler.headers['Content-Security-Policy'])
        self.assertEqual(handler.headers['Content-Type'], 'text/html; charset=utf-8')
        self.assertEqual(handler.headers['Cache-Control'], 'no-store')

    def test_the_report_route_reads_only_its_planet(self):
        # Serving one file must resolve only that planet's index, not walk the
        # workspace and choke on a sibling planet's broken index.
        other = self.workspace / 'planets/other/operations/leadership/reports'
        other.mkdir(parents=True)
        (other / 'index.json').write_text('{broken')
        body, mime = operation_reports.published_file(self.workspace, '/reports/example/' + self.row['path'])
        self.assertIn(b'Report', body)
        self.assertTrue(mime.startswith('text/html'))

    def test_unreadable_settings_answers_503(self):
        class Handler:
            def __init__(self): self.code = None; self.payload = None
            def _send_json(self, payload, status=200): self.code, self.payload = status, payload
        # An unreadable workspace settings file cannot scope publication.
        settings = self.workspace / '.solar/settings.json'
        settings.parent.mkdir()
        settings.write_text('{broken')
        handler = Handler()
        app_http.get(handler, '/reports/example/' + self.row['path'], {}, self.workspace)
        self.assertEqual(handler.code, 503)

    def test_absent_client_inventory_answers_503(self):
        class Handler:
            def __init__(self): self.code = None; self.payload = None
            def _send_json(self, payload, status=200): self.code, self.payload = status, payload
        handler = Handler()
        with patch.object(operation_reports, 'INVENTORY', self.workspace / 'missing_skill_inventory.py'):
            app_http.get(handler, '/reports/example/' + self.row['path'], {}, self.workspace)
        self.assertEqual(handler.code, 503)


class LegacyContinuityRoute(unittest.TestCase):
    def test_the_retired_screen_keeps_its_read_endpoint(self):
        from unittest.mock import patch
        import console_data

        class Handler:
            def _send_json(self, payload, status=200):
                self.payload, self.status = payload, status

        handler = Handler()
        with patch.object(console_data, 'continuity', return_value={'at': None, 'active': 'kept'}):
            app_http.get(handler, '/api/console/continuity', {}, '/nonexistent')
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload, {'at': None, 'active': 'kept'})


if __name__ == '__main__':
    unittest.main()
