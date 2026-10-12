"""Task detail: curated context by default, complete record only on request."""
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_console
import app_http
import console_data
import solar_state
from task_markdown import render_markdown, sanitize_html


class HostLoggingTests(unittest.TestCase):
    """The real `solar.app` logger and the root handlers are saved and restored around each test."""

    def setUp(self):
        import logging
        self.logging = logging
        self.logger = logging.getLogger('solar.app')
        self.root = logging.getLogger()
        self.saved = (self.logger.level, self.logger.propagate, list(self.logger.handlers), list(self.root.handlers))
        for handler in list(self.logger.handlers) + list(self.root.handlers):
            self.logger.removeHandler(handler)
            self.root.removeHandler(handler)
        self.addCleanup(self.restore)

    def restore(self):
        level, propagate, handlers, root_handlers = self.saved
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
        for handler in handlers:
            self.logger.addHandler(handler)
        for handler in root_handlers:
            self.root.addHandler(handler)
        self.logger.setLevel(level)
        self.logger.propagate = propagate

    def failing_task_detail(self):
        handler = Handler()
        with patch.object(console_data, 'task_detail', side_effect=sqlite3.DatabaseError('SECRET detail')):
            app_http.get(handler, '/api/console/task-detail', {'task_id': ['t']}, '/nonexistent')
        return handler

    def test_real_logger_writes_once_to_stderr_with_the_class_only(self):
        import io
        from contextlib import redirect_stderr
        import host_server
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            host_server.configure_logging()
            host_server.configure_logging()  # idempotent
            self.assertEqual(sum(getattr(h, '_solar_host', False) for h in self.logger.handlers), 1)
            handler = self.failing_task_detail()
        self.assertEqual(handler.status, 503)
        text = buffer.getvalue()
        self.assertEqual(text.count('DatabaseError'), 1)
        self.assertIn('task-detail failed', text)
        self.assertNotIn('SECRET', text)
        self.assertTrue(self.logger.propagate, 'propagation is left at its default')

    def test_a_configured_root_is_trusted_and_nothing_prints_twice(self):
        import io
        from contextlib import redirect_stderr
        import host_server
        sink = io.StringIO()
        root_handler = self.logging.StreamHandler(sink)
        self.root.addHandler(root_handler)
        self.root.setLevel(self.logging.WARNING)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            host_server.configure_logging()
            self.failing_task_detail()
        self.assertFalse(any(getattr(h, '_solar_host', False) for h in self.logger.handlers))
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(sink.getvalue().count('DatabaseError'), 1)
        self.assertNotIn('SECRET', sink.getvalue())

    def test_other_loggers_still_reach_the_root(self):
        """Propagation is untouched: a child of solar.app still reaches a root handler."""
        import io
        import host_server
        sink = io.StringIO()
        self.root.addHandler(self.logging.StreamHandler(sink))
        host_server.configure_logging()
        self.logging.getLogger('solar.app.child').warning('child line')
        self.assertIn('child line', sink.getvalue())

    def test_generic_handler_logs_the_class_and_answers_the_fixed_body(self):
        import io
        from contextlib import redirect_stderr
        import host_server
        sent = []
        handler = host_server.HostHandler.__new__(host_server.HostHandler)
        handler.path = '/api/console/health?x=1'
        handler._work_guard = lambda: True
        handler._send_json = lambda payload, code=200: sent.append((payload, code))
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            host_server.configure_logging()
            with patch.object(app_http, 'get', side_effect=OSError('SECRET /private/path')):
                handler.do_GET()
        self.assertEqual(sent, [({'error': 'Console data unavailable', 'refused': True}, 503)])
        text = buffer.getvalue()
        self.assertIn('OSError', text)
        self.assertIn("'/api/console/health'", text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('x=1', text)


class Handler:
    def _send_json(self, payload, status=200):
        self.payload, self.status = payload, status


class TaskDetailTests(unittest.TestCase):
    setUp = test_console.ConsoleTests.setUp
    task = test_console.ConsoleTests.task

    def get(self, qs):
        handler = Handler()
        app_http.get(handler, '/api/console/task-detail', qs, self.ws)
        return handler

    def test_default_response_is_curated_without_record_or_body(self):
        checkpoint = {'wait': 'Owner review', 'next_check': {'at': '2026-10-13', 'action': 'Review'}}
        task_id = self.task(
            extra='agent: fixture\ncontinuity_checkpoint: ' + json.dumps(checkpoint) + '\n'
                  'scheduled_time: 09:30\nscheduled_timezone: Europe/Madrid\nsecret_note: do not show\n',
            body='# Private instructions')
        handler = self.get({'task_id': [task_id]})
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload, {
            'id': task_id, 'context_error': None,
            'context': {'agent': 'fixture', 'continuity_checkpoint': checkpoint},
            'configuration': {'scheduled_time': '09:30', 'scheduled_timezone': 'Europe/Madrid'},
        })

    def test_full_adds_record_and_sanitized_body(self):
        task_id = self.task(extra='future_field: {broken JSON\n', body='# Hello\n\n<script>alert(1)</script>')
        with solar_state.session() as store:
            store.conn.execute('ALTER TABLE tasks ADD COLUMN future_column TEXT')
            store.conn.execute('UPDATE tasks SET future_column = ? WHERE id = ?', ('new value', task_id))
        for qs in ({'task_id': [task_id], 'full': ['true']}, {'task_id': [task_id], 'full': ['1', '1']},
                   {'task_id': [task_id], 'full': ['']}):
            self.assertNotIn('record', self.get(qs).payload)
        # A future column is invisible by default and visible only with full=1.
        self.assertNotIn('new value', json.dumps(self.get({'task_id': [task_id]}).payload))
        handler = self.get({'task_id': [task_id], 'full': ['1']})
        self.assertEqual(handler.status, 200)
        record = handler.payload['record']
        self.assertEqual(record['future_column'], 'new value')
        self.assertIn(['future_field', ' {broken JSON'], record['frontmatter'])
        self.assertEqual(handler.payload['body_html'], '<h1>Hello</h1><p>&lt;script&gt;alert(1)&lt;/script&gt;</p>')
        self.assertEqual(set(handler.payload), {'id', 'context', 'context_error', 'configuration', 'record', 'body_html'})

    def test_bad_requests_and_missing_task(self):
        self.assertEqual(self.get({}).status, 400)
        self.assertEqual(self.get({'task_id': ['x' * 201]}).status, 400)
        handler = self.get({'task_id': ['missing']})
        self.assertEqual((handler.status, handler.payload), (404, {'error': 'Task not found'}))

    def test_refusal_uses_fixed_message(self):
        secret = 'SECRET /private/path detail'
        for error in (solar_state.StateError(secret), ValueError(secret), sqlite3.OperationalError(secret),
                      RuntimeError(secret), KeyError(secret), json.JSONDecodeError(secret, '', 0)):
            with patch.object(console_data, 'task_detail', side_effect=error):
                handler = self.get({'task_id': ['task']})
            self.assertEqual(handler.status, 503)
            self.assertEqual(handler.payload, {'error': 'Task detail unavailable', 'refused': True})
            self.assertNotIn('SECRET', json.dumps(handler.payload))

    def test_unexpected_failure_in_the_real_read_path_is_fixed_503(self):
        task_id = self.task(body='# Body')
        secret = 'SECRET sqlite detail'
        with patch('runtime_views.console_task_detail', side_effect=sqlite3.DatabaseError(secret)):
            for qs in ({'task_id': [task_id]}, {'task_id': [task_id], 'full': ['1']}):
                with self.assertLogs('solar.app', level='WARNING') as logged:
                    handler = self.get(qs)
                self.assertEqual(handler.status, 503)
                self.assertEqual(handler.payload, {'error': 'Task detail unavailable', 'refused': True})
                self.assertNotIn('SECRET', json.dumps(handler.payload))
                log = '\n'.join(logged.output)
                self.assertIn('DatabaseError', log)
                self.assertNotIn('SECRET', log)

    def test_absent_or_non_string_body_gives_null_body_html(self):
        """Real case: a blob body. Contract case: a missing body, which the column
        (TEXT NOT NULL DEFAULT '') cannot hold, is only exercised through a mock."""
        for stored in (b'bytes',):
            task_id = self.task(task_id='body-' + type(stored).__name__, body='# Body')
            with solar_state.session() as store:
                store.conn.execute('UPDATE tasks SET body = ? WHERE id = ?', (stored, task_id))
            handler = self.get({'task_id': [task_id], 'full': ['1']})
            self.assertEqual(handler.status, 200, stored)
            self.assertIsNone(handler.payload['body_html'], stored)
            self.assertEqual(handler.payload['record']['body'], stored)
        for record in ({'id': 'x'}, {'id': 'x', 'body': None}):
            with patch.object(console_data, 'task_detail', return_value={'id': 'x', 'record': record}):
                handler = self.get({'task_id': ['x'], 'full': ['1']})
            self.assertEqual(handler.status, 200)
            self.assertIsNone(handler.payload['body_html'])

    def test_unreadable_frontmatter_is_200_not_503(self):
        task_id = self.task(body='## Keep these instructions')
        with solar_state.session() as store:
            store.conn.execute('UPDATE tasks SET frontmatter = ? WHERE id = ?', ('[broken', task_id))
        handler = self.get({'task_id': [task_id]})
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload, {'id': task_id, 'context': None,
                                           'context_error': 'frontmatter_unreadable', 'configuration': {}})
        handler = self.get({'task_id': [task_id], 'full': ['1']})
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload['record']['frontmatter'], '[broken')
        self.assertEqual(handler.payload['record']['status'], 'error')
        self.assertEqual(handler.payload['body_html'], '<h2>Keep these instructions</h2>')

    def test_invalid_checkpoint_is_a_stable_code(self):
        task_id = self.task(extra='continuity_checkpoint: []\nscheduled_timezone: Europe/Madrid\n')
        payload = self.get({'task_id': [task_id]}).payload
        self.assertEqual(payload['context_error'], 'checkpoint_invalid')
        self.assertIsNone(payload['context'])
        self.assertEqual(payload['configuration'], {'scheduled_timezone': 'Europe/Madrid'})

    def test_reads_open_no_write_session_and_change_nothing(self):
        task_id = self.task(extra='agent: fixture\n', body='# Body')
        with solar_state.read_session() as store:
            before = (store.task_get(task_id), [tuple(r) for r in store.conn.execute('SELECT * FROM task_events')])
        with patch.object(solar_state, 'session', side_effect=AssertionError('write session used')):
            self.get({'task_id': [task_id]})
            self.get({'task_id': [task_id], 'full': ['1']})
            self.assertIsNone(console_data.task_detail(self.ws, 'missing'))
        with solar_state.read_session() as store:
            after = (store.task_get(task_id), [tuple(r) for r in store.conn.execute('SELECT * FROM task_events')])
            self.assertEqual(store.conn.total_changes, 0)
        self.assertEqual(before, after)


class MarkdownTests(unittest.TestCase):
    def test_readable_markdown(self):
        rendered = render_markdown('# Title\n\n**Bold** and *emphasis* and `code`\n\n- First\n- Second\n\n1. Ordered\n\n> Quote\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint("<tag>")\n```\n\n[Source](https://example.test)')
        self.assertEqual(rendered, (
            '<h1>Title</h1><p><strong>Bold</strong> and <em>emphasis</em> and <code>code</code></p>'
            '<ul><li>First</li><li>Second</li></ul><ol><li>Ordered</li></ol>'
            '<blockquote>Quote</blockquote>'
            '<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>'
            '<pre><code>print(&quot;&lt;tag&gt;&quot;)</code></pre>'
            '<p><a href="https://example.test" rel="noreferrer noopener">Source</a></p>'))

    def test_underscores_are_text(self):
        for text in ('task_id and user_id', '__init__', 'a _b_ c', '__bold__'):
            self.assertEqual(render_markdown(text), '<p>' + text + '</p>')

    def test_asterisks_need_tight_marks_and_clean_outside(self):
        for text in ('1 * 2 * 3', '2*3*4', 'a ** b ** c', '**bold**text', 'x*y*'):
            self.assertEqual(render_markdown(text), '<p>' + text + '</p>')
        self.assertEqual(render_markdown('(*a*) and **b**'), '<p>(<em>a</em>) and <strong>b</strong></p>')

    def test_only_explicit_safe_schemes_become_links(self):
        for target in ('/relative', 'relative/path', '#frag', '', '//evil.test', 'javascript:alert', 'data:text/html,x',
                       'vbscript:alert', 'java&#x73;cript:alert', 'JaVaScRiPt:x', 'https://[broken', 'ftp://x.test',
                       'https:evil', 'http://'):
            rendered = render_markdown('[label](' + target + ')')
            self.assertEqual(rendered, '<p>label</p>', target)
        self.assertEqual(render_markdown('[a](HTTP://Example.test/x?y=1) [m](mailto:a@b.test)'),
                         '<p><a href="HTTP://Example.test/x?y=1" rel="noreferrer noopener">a</a> '
                         '<a href="mailto:a@b.test" rel="noreferrer noopener">m</a></p>')

    def test_entity_like_text_in_a_query_stays_a_link_but_encoded_schemes_do_not(self):
        rendered = render_markdown('[a](https://x.com/?a=1&copy=2&reg=3&sect=4)')
        self.assertEqual(rendered, '<p><a href="https://x.com/?a=1&amp;copy=2&amp;reg=3&amp;sect=4" '
                                   'rel="noreferrer noopener">a</a></p>')
        for target in ('java&#x73;cript:alert', 'java&#115;cript:alert', 'javascript&colon;alert', 'jav&Tab;ascript:x',
                       'javascript:alert', 'data:text/html,x', '//evil.test', '/relative'):
            self.assertEqual(render_markdown('[l](' + target + ')'), '<p>l</p>', target)
        # An anchor that reaches the sanitizer with an entity-encoded scheme is dropped too.
        self.assertEqual(sanitize_html('<a href="java&#x73;cript:alert(1)">x</a>'), 'x')
        self.assertEqual(sanitize_html('<a href="https://x.com/?a=1&amp;copy=2">x</a>'),
                         '<a href="https://x.com/?a=1&amp;copy=2" rel="noreferrer noopener">x</a>')

    def test_authority_must_be_a_plain_host(self):
        for target in ('https://evil.test@good.test/x', 'https://foo.com&copy=1&x=y', 'https://user:pw@x.test/',
                       'https://a b.test/', 'https://x.test:port/', 'https://-bad.test/', 'https://x.test:123456/',
                       'https://x=y.test/', 'https://x.test@/', 'http://[1]/', 'http://[:::]/', 'http://[::1/', 'http://[....]/',
                       'http://[::1]]/', 'http://[::ffff:1.2.3.4]/', 'http://[::ffff:102:304]/', 'http://[::1.2.3.4]/',
                       'http://[64:ff9b::1.2.3.4]/', 'https://a-.test/', 'https://-a.test/', 'https://a.-b.test/', 'https://a.b-.test/',
                       'https://' + 'a' * 64 + '.test/', 'https://x..test/', 'https://x.test./', 'http://[12345::1]/', 'http://[::g]/', 'http://[1:2:3:4:5:6:7:8:9]/', 'https://x.test:99999/', 'https://x.test:0/',
                       'https://x.test:65536/', 'http://[::1]:0/', 'https://münchen.de/', 'https://xn--mnchen-3ya.de@evil.test/'):
            self.assertNotIn('<a', render_markdown('[l](' + target + ')'), target)
        for target in ('https://x.com/?a=1&copy=2', 'http://localhost:9000/a', 'https://sub.x-y.example.org/p#f',
                       'http://127.0.0.1/', 'http://[::1]:8080/x', 'https://x.test:1/', 'https://x.test:65535/', 'https://a-b.test/', 'https://' + 'a' * 63 + '.test/',
                       'https://[::1]/x', 'http://[2001:db8::1]:8080/x', 'https://xn--mnchen-3ya.de/'):
            self.assertIn('<a href="', render_markdown('[l](' + target + ')'), target)
        self.assertEqual(sanitize_html('<a href="https://evil.test@good.test/">x</a>'), 'x')

    def test_internationalized_hosts_stay_text(self):
        """Documented limitation: a non-ASCII host is never linked; its punycode form is."""
        rendered = render_markdown('[l](https://münchen.de/x)')
        self.assertNotIn('<a', rendered)
        self.assertIn('l', rendered)
        self.assertIn('<a href="https://xn--mnchen-3ya.de/x"', render_markdown('[l](https://xn--mnchen-3ya.de/x)'))

    def test_consecutive_quote_lines_form_one_blockquote(self):
        self.assertEqual(render_markdown('> one\n> two\n>three\n\n> next'),
                         '<blockquote>one<br>two<br>three</blockquote><blockquote>next</blockquote>')

    def test_horizontal_rules_beat_lists(self):
        self.assertEqual(render_markdown('---\n***\n___\n* * *\n- - -\n_ _ _'), '<hr>' * 6)
        self.assertEqual(render_markdown('a\n\n---\n\n- item'), '<p>a</p><hr><ul><li>item</li></ul>')
        self.assertEqual(render_markdown('--'), '<p>--</p>')

    def test_unsafe_html_and_images_stay_inert(self):
        rendered = render_markdown('<img src=x onerror=alert(1)>\n\n<svg/onload=alert(2)>\n\n![image](https://evil.test/image)')
        for forbidden in ('<img', '<svg', '<a '):
            self.assertNotIn(forbidden, rendered)
        self.assertIn('&lt;img', rendered)

    def test_allowlist_strips_attributes_elements_and_unsafe_anchors(self):
        result = sanitize_html('<p style="color:red" onclick="alert(1)">Safe</p><script>alert(2)</script><iframe src="x"></iframe><a href="javascript:alert(3)" onfocus="bad">Link</a><a>None</a><a href="/rel">Rel</a><a href="https://ok.test/?a=1&amp;b=2">Ok</a>')
        self.assertEqual(result, '<p>Safe</p>alert(2)LinkNoneRel<a href="https://ok.test/?a=1&amp;b=2" rel="noreferrer noopener">Ok</a>')
        self.assertNotIn('<a>', result)

    def test_malformed_content_and_fallback(self):
        self.assertIsNone(render_markdown({'invalid': 'body type'}))
        self.assertIn('&lt;script&gt;', render_markdown('```\n<script>'))
        self.assertIn('**unfinished', render_markdown('**unfinished'))
        with patch('task_markdown._markdown', side_effect=ValueError('bad Markdown')):
            self.assertEqual(render_markdown('<script>'), '<pre>&lt;script&gt;</pre>')
