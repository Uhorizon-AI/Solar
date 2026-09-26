"""Console regression tests use isolated canonical sources; no live mutations."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[3] / 'skills/solar-app/scripts'
sys.path.insert(0, str(SCRIPTS))
import app_solar
import host_server
import host_workspace_context as context
from http.server import ThreadingHTTPServer


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / 'workspace'
        (self.ws / 'sun').mkdir(parents=True)
        # Machine state lives outside the workspace: the console must read the
        # runtime root, and must never look inside sun/.
        app_data = Path(self.tmp.name) / 'AppData'
        app_data.mkdir()
        patcher = patch.dict(os.environ, {'SOLAR_APP_DATA': str(app_data), 'SOLAR_RUNTIME_ROOT': ''})
        patcher.start()
        self.addCleanup(patcher.stop)
        runtime = app_solar.runtime_dir()
        self.runtime = runtime
        for name in ('async-tasks', 'router', 'gateway', 'continuity'):
            (runtime / name).mkdir(parents=True)
        for state in app_solar.TASK_STATES:
            (runtime / 'async-tasks' / state).mkdir()
        self.audit = runtime / 'router/audit.jsonl'
        self.audit.write_text('')
        import solar_state
        with solar_state.cutover(runtime) as cut:
            cut.upgrade_schema()
            cut.set_format('sqlite')

    def task(self, state='error', extra='', body='## Execution Error\n- error: provider unavailable', task_id='task', log_path=None):
        import solar_state
        status = {'drafts': 'draft', 'archive': 'archived'}.get(state, state)
        document = (
            f'---\nid: {task_id}\ntitle: A task\ncreated: 2020-01-01T00:00:00Z\n'
            f'provider: codex\n{extra}status: {status}\n---\n{body}'
        )
        with solar_state.session() as store:
            store.task_import(document, status=status, log_path=str(log_path) if log_path else None)
        return task_id

    def write_audit(self, *rows):
        import solar_state
        with solar_state.session() as store:
            for row in rows:
                store.audit_append(row)

    def assertWorkspaceUntouched(self):
        """No machine state may appear inside sun/ while the console runs."""
        self.assertEqual(sorted(p.name for p in (self.ws / 'sun').iterdir()), [])

    def test_discovers_all_real_states_without_turning_task_error_into_bad_storage(self):
        for state in app_solar.TASK_STATES:
            self.task(state, task_id=f'task-{state}')
        data = app_solar.snapshot(self.ws)
        self.assertEqual({t['state'] for t in data['tasks']}, set(app_solar.TASK_STATES))
        self.assertTrue(data['health']['storage_ok'])
        self.assertEqual(data['health']['status'], 'unverified')
        self.assertFalse((self.runtime/'app').exists())
        self.assertWorkspaceUntouched()
        self.assertTrue(next(t for t in data['tasks'] if t['state']=='drafts')['stale'])

    def test_recurring_count_origin_and_outputs(self):
        self.task('queued', 'recurring: true\nrecurring_run_count: 830\norigin_channel: telegram\n', '## Result\nDone [report](sun/report.md)')
        task = app_solar.read_tasks(self.ws)[0][0]
        self.assertEqual(task['recurring_run_count'], '830')
        self.assertEqual(task['origin'], 'telegram')
        self.assertEqual(task['artifacts'], ['sun/report.md'])

    def test_explicit_output_below_nested_result_heading(self):
        self.assertEqual(app_solar.artifacts('## Result\nDone\n## Report\nSaved to: `sun/report.md`', {}), ['sun/report.md'])

    def test_task_log_reports_used_provider_not_requested_provider(self):
        log = self.runtime / 'task-logs' / 'task.log'
        log.parent.mkdir()
        log.write_text('- task_id: task\n- provider_used: agent\n## Result\nPrepared report')
        self.task('completed', log_path=log)
        task = app_solar.read_tasks(self.ws)[0][0]
        self.assertEqual(task['provider'], 'agent')
        self.assertEqual(task['provider_requested'], 'codex')
        self.assertEqual(task['summary'], 'Prepared report')

    def test_pairs_router_records_and_preserves_zero_and_false(self):
        self.write_audit(
            dict(event='start', router_id='r', user_id='independent-reviewer', channel='other', ts=app_solar.iso()),
            dict(event='end', router_id='r', status='success', provider='agent', history_turns=0, summary_used=False, duration_ms=71000, ts=app_solar.iso()))
        runs, errors = app_solar.read_router(self.ws)
        self.assertFalse(errors)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['user_id'], 'independent-reviewer')
        self.assertEqual(runs[0]['history_turns'], 0)
        self.assertIs(runs[0]['summary_used'], False)
        self.assertEqual(runs[0]['duration_ms'], 71000)

    def test_old_unclosed_router_start_is_not_working(self):
        self.write_audit(dict(event='start', router_id='old', ts='2020-01-01T00:00:00Z'))
        data=app_solar.snapshot(self.ws)
        self.assertEqual(data['working'], 0)
        self.assertEqual(data['executions'][0]['state'], 'unverified')

    def test_router_response_is_paged_but_counts_cover_all_runs(self):
        rows=[]
        for number in range(55):
            rid=f'r{number}'
            rows.extend((dict(event='start',router_id=rid,ts=app_solar.iso()),
                         dict(event='end',router_id=rid,status='failed' if number < 7 else 'success',ts=app_solar.iso())))
        self.write_audit(*rows)
        data=app_solar.snapshot(self.ws)
        self.assertEqual(len(data['executions']), app_solar.PAGE_SIZE)
        self.assertEqual(data['counts']['executions'], 55)
        self.assertEqual(data['counts']['errors'], 7)
        page=app_solar.activity_page(self.ws, 'router', '', 40, 40)
        self.assertEqual(len(page['items']), 15)
        self.assertFalse(page['has_more'])

    def test_session_failure_marks_storage_unreadable(self):
        data=app_solar.snapshot(self.ws)
        self.assertTrue(data['health']['storage_ok'])
        with patch.object(app_solar.solar_state, 'session', side_effect=app_solar.solar_state.StateError('denied')):
            self.assertFalse(app_solar.snapshot(self.ws)['health']['storage_ok'])

    def test_mount_ignores_legacy_workspace_ports(self):
        (self.ws/'.env').write_text('SOLAR_APP_PORT=9434\nSOLAR_HOST_PORT=9221\n')
        with patch.dict(os.environ, {}, clear=True):
            context.mount(str(self.ws))
            self.assertEqual(os.environ['SOLAR_APP_PORT'], '9000')
            self.assertNotIn('SOLAR_HOST_PORT', os.environ)
            context.unmount()

    def test_gateway_failure_dates_and_stale_continuity(self):
        runtime=self.runtime
        (runtime/'gateway/env.fail').write_text('reason=tunnel_recovery_failed\nfailed_at=1788787951\nexhausted=1\nattempts=5\nnext_retry_at=1820323951\n')
        import solar_state
        with solar_state.session() as store:
            store.continuity_import_text(json.dumps(dict(active_task='Incomplete intention', updated_at='2020-01-01T00:00:00Z')) + '\n')
        data=app_solar.snapshot(self.ws)
        self.assertEqual(data['health']['status'],'problems')
        gateway=next(c for c in data['health']['components'] if c['component']=='gateway')
        self.assertTrue(gateway['exhausted'])
        self.assertIn('2027',gateway['next_retry_at'])
        continuity=next(c for c in data['health']['components'] if c['component']=='continuity')
        self.assertTrue(continuity['stale'])
        self.assertWorkspaceUntouched()

    def test_mount_never_creates_conversation_store(self):
        with patch.dict(os.environ,{},clear=False):
            context.mount(str(self.ws))
            self.assertFalse((self.runtime/'app').exists())
            context.unmount()

    def test_http_console_and_retired_routes(self):
        with patch.object(host_server,'_active_workspace',return_value=self.ws):
            server=ThreadingHTTPServer(('127.0.0.1',0),host_server.HostHandler)
            port=server.server_address[1]
            with patch.object(host_server,'PORT',port):
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    base='http://127.0.0.1:'+str(port)
                    with urllib.request.urlopen(base+'/') as response:
                        html=response.read().decode()
                    self.assertIn('id="health"',html)
                    self.assertNotIn('<textarea',html)
                    self.assertNotIn('data-action=',html)
                    with urllib.request.urlopen(base+'/api/runtime/health') as response:
                        self.assertTrue(json.load(response)['storage_ok'])
                    with urllib.request.urlopen(base+'/health') as response:
                        self.assertTrue(json.load(response)['process_ok'])
                    (self.runtime / 'state.sqlite').unlink()
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(base+'/api/runtime/health')
                    self.assertEqual(raised.exception.code, 503)
                    raised.exception.close()
                    for path in ('/api/chat','/api/app/conversations','/api/voice/turn','/api/approvals','/api/threads'):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(base+path)
                        self.assertEqual(raised.exception.code,404)
                        raised.exception.close()
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(urllib.request.Request(base+path,data=b'{}'))
                        self.assertEqual(raised.exception.code,405)
                        raised.exception.close()
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(urllib.request.Request(base+'/api/app/bootstrap',headers={'Host':'evil.example'}))
                    self.assertEqual(raised.exception.code,403)
                    raised.exception.close()
                finally:
                    server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
