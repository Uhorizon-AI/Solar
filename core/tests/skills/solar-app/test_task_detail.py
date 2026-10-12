"""Complete task records are read-only; malformed content stays presentable."""
import sqlite3
import unittest
from unittest.mock import patch

import test_console
import app_http
import console_data
import solar_state
from task_markdown import render_markdown, sanitize_html


class TaskDetailTests(unittest.TestCase):
    setUp = test_console.ConsoleTests.setUp
    task = test_console.ConsoleTests.task

    def test_full_record_future_column_and_frontmatter_without_writes(self):
        task_id = self.task(extra='future_field: {broken JSON\n', body='# Instructions\n\nDo **this**.')
        with solar_state.session() as store:
            store.conn.execute('ALTER TABLE tasks ADD COLUMN future_column TEXT')
            store.conn.execute('UPDATE tasks SET future_column = ? WHERE id = ?', ('new value', task_id))
            before = store.task_get(task_id)
            events = [tuple(row) for row in store.conn.execute('SELECT * FROM task_events')]
        with patch.object(solar_state, 'session', side_effect=AssertionError('write session used')):
            record = console_data.task_detail(self.ws, task_id)
            self.assertEqual(record, before)
            self.assertEqual(record['future_column'], 'new value')
            self.assertIn(['future_field', ' {broken JSON'], record['frontmatter'])
            self.assertEqual(record['body'], '# Instructions\n\nDo **this**.')
            self.assertIsNone(console_data.task_detail(self.ws, 'missing'))
        with solar_state.read_session() as store:
            self.assertEqual(store.task_get(task_id), before)
            self.assertEqual([tuple(row) for row in store.conn.execute('SELECT * FROM task_events')], events)
            self.assertEqual(store.conn.total_changes, 0)
            with self.assertRaises(sqlite3.OperationalError):
                store.conn.execute('UPDATE tasks SET body = body')

    def test_corrupt_frontmatter_does_not_hide_other_columns(self):
        task_id = self.task(body='## Keep these instructions')
        with solar_state.session() as store:
            store.conn.execute('UPDATE tasks SET frontmatter = ? WHERE id = ?', ('[broken', task_id))
        record = console_data.task_detail(self.ws, task_id)
        self.assertEqual(record['frontmatter'], '[broken')
        self.assertEqual(record['body'], '## Keep these instructions')
        self.assertEqual(record['status'], 'error')

    def test_endpoint_returns_full_record_and_only_renders_body(self):
        task_id = self.task(extra='new_field: [bad\n', body='# Hello\n\n<script>alert(1)</script>')
        class Handler:
            def _send_json(self, payload, status=200):
                self.payload, self.status = payload, status
        handler = Handler()
        app_http.get(handler, '/api/console/task-detail', {'task_id': [task_id]}, self.ws)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload['record'], console_data.task_detail(self.ws, task_id))
        self.assertIn('<h1>Hello</h1>', handler.payload['body_html'])
        self.assertNotIn('<script>', handler.payload['body_html'])
        self.assertIn('&lt;script&gt;', handler.payload['body_html'])
        app_http.get(handler, '/api/console/task-detail', {'task_id': ['missing']}, self.ws)
        self.assertEqual(handler.status, 404)
        app_http.get(handler, '/api/console/task-detail', {}, self.ws)
        self.assertEqual(handler.status, 400)


class MarkdownTests(unittest.TestCase):
    def test_readable_markdown(self):
        rendered = render_markdown('# Title\n\n**Bold** and *emphasis* and `code`\n\n- First\n- Second\n\n1. Ordered\n\n> Quote\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint("<tag>")\n```\n\n[Source](https://example.test)')
        for tag in ('<h1>', '<strong>', '<em>', '<code>', '<ul>', '<ol>', '<blockquote>', '<table>', '<pre>'):
            self.assertIn(tag, rendered)
        self.assertIn('&lt;tag&gt;', rendered)
        self.assertIn('href="https://example.test"', rendered)

    def test_unsafe_html_and_urls(self):
        rendered = render_markdown('<img src=x onerror=alert(1)>\n\n<svg/onload=alert(2)>\n\n[bad](javascript:alert) [bad](data:text/html,x) [bad](vbscript:alert) [bad](//evil.test) [bad](java&#x73;cript:alert) [bad](https://[broken)\n\n![image](https://evil.test/image)')
        for forbidden in ('<img', '<svg', 'href="javascript:', 'href="data:', 'href="vbscript:', 'href="//', 'href="https://[broken'):
            self.assertNotIn(forbidden, rendered)
        self.assertIn('&lt;img', rendered)

    def test_allowlist_strips_attributes_and_disallowed_elements(self):
        result = sanitize_html('<p style="color:red" onclick="alert(1)">Safe</p><script>alert(2)</script><iframe src="x"></iframe><a href="javascript:alert(3)" onfocus="bad">Link</a>')
        self.assertEqual(result, '<p>Safe</p>alert(2)<a>Link</a>')

    def test_malformed_content_and_fallback(self):
        self.assertIsNone(render_markdown({'invalid': 'body type'}))
        self.assertIn('&lt;script&gt;', render_markdown('```\n<script>'))
        self.assertIn('**unfinished', render_markdown('**unfinished'))
        with patch('task_markdown._markdown', side_effect=ValueError('bad Markdown')):
            self.assertEqual(render_markdown('<script>'), '<pre>&lt;script&gt;</pre>')
