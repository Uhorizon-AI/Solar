"""Publication confines report files; it never turns the console into a file server."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

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
        self.assertEqual(handler.headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()


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
