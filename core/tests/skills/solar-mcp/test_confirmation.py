"""Confirmation belongs to the client transport, never to tool arguments."""
import json
import threading
from io import StringIO

import pytest

import mcp_approve
import mcp_gate
import mcp_server


def request(arguments=None):
    return dict(jsonrpc='2.0', id=2, method='tools/call', params=dict(
        name='solar_task_create', arguments=arguments or {'title': 'Approved task'}))


def test_confirmed_action_creates_internal_approval(solar_env, monkeypatch):
    seen = []
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: seen.append(args) or {'ok': True})
    response = mcp_server.handle(request(), lambda name, args, rid: True)
    assert not response['result']['isError']
    assert seen[0]['approval_id']
    assert mcp_approve.listing()[0]['consumed_at']


def test_declined_action_does_not_mint(solar_env):
    response = mcp_server.handle(request(), lambda *args: False)
    assert response['result']['isError']
    assert not mcp_approve.listing()


def test_forged_tool_flag_cannot_authorize(solar_env):
    response = mcp_server.handle(request({'title': 'X', 'approved': True}), lambda *args: True)
    assert response['error']['code'] == -32602
    assert not mcp_approve.listing()


def test_explicit_recipient_required_for_confirmation(solar_env):
    message = request()
    message['params'] = dict(name='solar_telegram_send', arguments={'text': 'hello'})
    assert mcp_server.handle(message, lambda *args: True)['error']['code'] == -32602


def test_failed_execution_burns_approval(solar_env, monkeypatch):
    granted = mcp_approve.grant('solar_task_create', {'title': 'X'}, 900, 'test')
    args = {'title': 'X', 'approval_id': granted['approval_id']}
    def fail(arguments):
        raise RuntimeError('uncertain result')
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', fail)
    assert mcp_server.call_tool('solar_task_create', args)[1]
    assert mcp_server.call_tool('solar_task_create', args)[0]['refused']['code'] == 'approval_consumed'


def test_approval_bound_to_workspace(solar_env, monkeypatch):
    granted = mcp_approve.grant('solar_task_create', {'title': 'X'}, 900, 'test')
    monkeypatch.setenv('SOLAR_WORKSPACE', str(solar_env.tmp_path / 'other'))
    verdict = mcp_gate.preflight('solar_task_create', {'title': 'X', 'approval_id': granted['approval_id']}, mcp_server.TOOLS)
    assert verdict.code == 'approval_scope_mismatch'


def test_two_workers_cannot_reuse_approval(solar_env, monkeypatch):
    seen = []
    granted = mcp_approve.grant('solar_task_create', {'title': 'X'}, 900, 'test')
    args = {'title': 'X', 'approval_id': granted['approval_id']}
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: seen.append(True))
    threads = [threading.Thread(target=mcp_server.call_tool, args=('solar_task_create', args)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert seen == [True]


@pytest.mark.parametrize('reply,expected', [
    ({'action': 'accept', 'content': {'approve': True}}, True),
    ({'action': 'accept', 'content': {'approve': 'true'}}, False),
    ({'action': 'accept', 'content': {}}, False),
    ({'action': 'decline'}, False),
    ({'action': 'cancel'}, False),
])
def test_transport_confirmation_matches_server_request(solar_env, monkeypatch, reply, expected):
    """A fake client responds to the generated ID as a real harness would."""
    import queue
    lines = queue.Queue()
    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=5)
                if line is None:
                    return
                yield line
    class Output(StringIO):
        def write(self, text):
            result = super().write(text)
            message = json.loads(text)
            if message.get('method') == 'elicitation/create':
                assert message['params']['requestedSchema']['properties']['approve']['default'] is False
                lines.put(json.dumps(dict(jsonrpc='2.0', id=message['id'], result=reply)))
                lines.put(None)
            return result
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: {'ok': True})
    lines.put(json.dumps(dict(jsonrpc='2.0', id=1, method='initialize', params=dict(capabilities={'elicitation': {}}))))
    lines.put(json.dumps(request()))
    output = Output()
    mcp_server.serve(Input(), output)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert messages[-1]['id'] == 2
    assert messages[-1]['result']['isError'] is not expected
    assert bool(mcp_approve.listing()) is expected


def test_unadvertised_confirmation_does_not_prompt(solar_env):
    lines = [dict(jsonrpc='2.0', id=1, method='initialize', params={'capabilities': {}}), request()]
    output = StringIO()
    mcp_server.serve(StringIO('\n'.join(map(json.dumps, lines))), output)
    messages = list(map(json.loads, output.getvalue().splitlines()))
    assert all(message.get('method') != 'elicitation/create' for message in messages)
    assert messages[-1]['result']['isError']
    assert not mcp_approve.listing()


def test_changed_recipient_rejected(solar_env):
    args = {'text': 'hello', 'chat_id': '123'}
    granted = mcp_approve.grant('solar_telegram_send', args, 900, 'test')
    verdict = mcp_gate.preflight('solar_telegram_send', dict(args, chat_id='456', approval_id=granted['approval_id']), mcp_server.TOOLS)
    assert verdict.code == 'approval_scope_mismatch'


@pytest.mark.parametrize('cancel', [False, True])
def test_interleaved_requests_are_retained(solar_env, monkeypatch, cancel):
    import queue
    lines = queue.Queue()
    observed = []
    real_handle = mcp_server.handle
    def handle(message, confirm=None):
        observed.append(message.get('method'))
        return real_handle(message, confirm)
    monkeypatch.setattr(mcp_server, 'handle', handle)
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: {'ok': True})
    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=5)
                if line is None:
                    return
                yield line
    class Output(StringIO):
        def write(self, text):
            result = super().write(text)
            message = json.loads(text)
            if message.get('method') == 'elicitation/create':
                for item in [
                    dict(jsonrpc='2.0', id=3, method='ping'),
                    dict(jsonrpc='2.0', method='notifications/initialized'),
                    dict(jsonrpc='2.0', id=4, method='tools/list'),
                    dict(jsonrpc='2.0', method='notifications/cancelled', params={'requestId': 2}) if cancel else
                    dict(jsonrpc='2.0', id=message['id'], result={'action':'accept', 'content':{'approve':True}}),
                ]:
                    lines.put(json.dumps(item))
                lines.put(None)
            return result
    lines.put(json.dumps(dict(jsonrpc='2.0', id=1, method='initialize', params={'capabilities':{'elicitation':{}}})))
    lines.put(json.dumps(request()))
    output = Output()
    mcp_server.serve(Input(), output)
    messages = list(map(json.loads, output.getvalue().splitlines()))
    replies = {item['id']: item for item in messages if 'method' not in item}
    assert replies[3]['result'] == {}
    assert 'tools' in replies[4]['result']
    assert 'notifications/initialized' in observed
    assert (2 in replies) is not cancel
    assert bool(mcp_approve.listing()) is not cancel


def test_confirmation_timeout_does_not_grant(solar_env, monkeypatch):
    monkeypatch.setattr(mcp_server, 'CONFIRMATION_TIMEOUT', 0)
    stream = StringIO('\n'.join(map(json.dumps, [
        dict(jsonrpc='2.0', id=1, method='initialize', params={'capabilities':{'elicitation':{}}}), request()])))
    output = StringIO()
    mcp_server.serve(stream, output)
    assert not mcp_approve.listing()
    assert json.loads(output.getvalue().splitlines()[-1])['result']['isError']


def test_unknown_schema_type_fails_closed(solar_env, monkeypatch):
    import copy
    spec = copy.deepcopy(mcp_server.TOOLS['solar_task_create'])
    spec['inputSchema']['properties']['title']['type'] = 'object'
    monkeypatch.setitem(mcp_server.TOOLS, 'solar_task_create', spec)
    result = mcp_server.handle(request(), lambda *args: True)
    assert result['error']['code'] == -32602
    assert not mcp_approve.listing()


@pytest.mark.parametrize('mode', ['origin', 'form', 'timeout', 'deferred'])
def test_cancel_closes_form_and_skips_deferred(solar_env, monkeypatch, mode):
    import queue
    lines = queue.Queue()
    effects = []
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: effects.append(args['title']))
    if mode == 'timeout':
        monkeypatch.setattr(mcp_server, 'CONFIRMATION_TIMEOUT', 0)
    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=5)
                if line is None:
                    return
                yield line
    class Output(StringIO):
        def write(self, text):
            result = super().write(text)
            message = json.loads(text)
            if message.get('method') == 'elicitation/create':
                eid = message['id']
                if mode == 'deferred':
                    later = request({'title': 'Cancelled later'})
                    later['id'] = 3
                    lines.put(json.dumps(later))
                    target = 3
                else:
                    target = eid if mode == 'form' else 2
                if mode != 'timeout':
                    lines.put(json.dumps(dict(jsonrpc='2.0', method='notifications/cancelled', params={'requestId':target})))
                # An acceptance after cancellation/expiry must not execute.
                lines.put(json.dumps(dict(jsonrpc='2.0', id=eid, result={'action':'accept','content':{'approve':True}})))
                lines.put(None)
            return result
    lines.put(json.dumps(dict(jsonrpc='2.0', id=1, method='initialize', params={'capabilities':{'elicitation':{}}})))
    lines.put(json.dumps(request()))
    output = Output()
    mcp_server.serve(Input(), output)
    messages = list(map(json.loads, output.getvalue().splitlines()))
    forms = [item for item in messages if item.get('method') == 'elicitation/create']
    assert len(forms) == 1
    if mode in ('origin', 'timeout'):
        assert any(item.get('method') == 'notifications/cancelled' and item['params']['requestId'] == forms[0]['id'] for item in messages)
    if mode == 'origin':
        assert not any(item.get('id') == 2 and 'method' not in item for item in messages)
    assert effects == (['Approved task'] if mode == 'deferred' else [])
    assert not any(item.get('id') == 3 and 'method' not in item for item in messages)


@pytest.mark.parametrize('deferred_cancel', [False, True])
def test_cancelled_id_can_be_reused(solar_env, monkeypatch, deferred_cancel):
    import queue
    lines = queue.Queue()
    effects = []
    forms = []
    reused_id = 3 if deferred_cancel else 2
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: effects.append(args['title']))
    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=5)
                if line is None:
                    return
                yield line
    def put(message):
        lines.put(json.dumps(message))
    class Output(StringIO):
        def write(self, text):
            result = super().write(text)
            message = json.loads(text)
            if message.get('method') == 'elicitation/create':
                forms.append(message['id'])
                if len(forms) == 1:
                    if deferred_cancel:
                        old = request({'title': 'Must not execute'})
                        old['id'] = reused_id
                        put(old)
                    put(dict(jsonrpc='2.0', method='notifications/cancelled', params={'requestId': reused_id}))
                    if deferred_cancel:
                        put(dict(jsonrpc='2.0', id=message['id'], result={'action':'decline'}))
                    new = request({'title': 'Reused ID'})
                    new['id'] = reused_id
                    put(new)
                    # EOF makes a regression fail instead of hanging forever.
                    # Acceptance is enqueued when the second form appears.
                else:
                    put(dict(jsonrpc='2.0', id=message['id'], result={'action':'accept','content':{'approve':True}}))
                    lines.put(None)
            return result
    put(dict(jsonrpc='2.0', id=1, method='initialize', params={'capabilities':{'elicitation':{}}}))
    put(request())
    output = Output()
    # Avoid hanging on old code which silently drops the reused request.
    worker = threading.Thread(target=mcp_server.serve, args=(Input(), output), daemon=True)
    worker.start()
    worker.join(timeout=3)
    if worker.is_alive():
        lines.put(None)
        worker.join(timeout=2)
    messages = list(map(json.loads, output.getvalue().splitlines()))
    assert len(forms) == 2
    assert effects == ['Reused ID']
    replies = [item for item in messages if item.get('id') == reused_id and 'method' not in item]
    assert len(replies) == 1
    assert not replies[0]['result']['isError']


@pytest.mark.parametrize('late_id', [2, 99])
def test_late_or_unknown_cancel_does_not_poison_reused_id(solar_env, monkeypatch, late_id):
    import queue
    lines = queue.Queue()
    effects = []
    replies = []
    monkeypatch.setitem(mcp_server.HANDLERS, 'solar_task_create', lambda args: effects.append(args['title']))
    def put(message):
        lines.put(json.dumps(message))
    class Input:
        def __iter__(self):
            while True:
                line = lines.get(timeout=5)
                if line is None:
                    return
                yield line
    class Output(StringIO):
        def write(self, text):
            result = super().write(text)
            message = json.loads(text)
            if message.get('method') == 'elicitation/create':
                put(dict(jsonrpc='2.0', id=message['id'], result={'action':'accept','content':{'approve':True}}))
            elif 'method' not in message and message.get('id') in (2, 99):
                replies.append(message)
                if len(replies) == 1:
                    # Send only after receiving the first completed response.
                    put(dict(jsonrpc='2.0', method='notifications/cancelled', params={'requestId':late_id}))
                    next_call = request({'title': 'Second call'})
                    next_call['id'] = late_id
                    put(next_call)
                else:
                    lines.put(None)
            return result
    put(dict(jsonrpc='2.0', id=1, method='initialize', params={'capabilities':{'elicitation':{}}}))
    put(request())
    output = Output()
    worker = threading.Thread(target=mcp_server.serve, args=(Input(), output), daemon=True)
    worker.start()
    worker.join(timeout=3)
    timed_out = worker.is_alive()
    if timed_out:
        lines.put(None)
        worker.join(timeout=2)
    assert not timed_out, 'Server dropped a call after a stale cancellation'
    assert len(replies) == 2
    assert all(not reply['result']['isError'] for reply in replies)
    assert effects == ['Approved task', 'Second call']
