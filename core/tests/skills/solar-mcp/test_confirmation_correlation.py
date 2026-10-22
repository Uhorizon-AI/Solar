"""Native form routing metadata never supplies approval authority."""
import json
import queue
from io import StringIO

import pytest

import mcp_approve
import mcp_server
import operations


def execute(rid, meta):
    return dict(jsonrpc='2.0', id=rid, method='tools/call', params=dict(
        name='solar_execute', _meta=meta, arguments=dict(
            operation='task.create', arguments=dict(title=f'Fixture {rid}', instructions='x'))))


def transport(messages, reply):
    lines = queue.Queue()
    forms = []
    for message in [dict(jsonrpc='2.0', id=1, method='initialize',
                         params={'capabilities': {'elicitation': {'form': {}}}}), *messages]:
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
                forms.append(message)
                lines.put(json.dumps(dict(jsonrpc='2.0', id=message['id'], result=reply)))
                if len(forms) == len(messages):
                    lines.put(None)
            return result

    output = Output()
    mcp_server.serve(Input(), output)
    return forms, [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize('meta,expected', [
    (None, None),
    ({}, None),
    ([], None),
    ('invalid', None),
    ({'progressToken': 'conversation', 'approved': True, 'unrelated': 'private'},
     {'progressToken': 'conversation'}),
    ({'progressToken': ''}, {'progressToken': ''}),
    ({'progressToken': 0}, {'progressToken': 0}),
    ({'progressToken': 42}, {'progressToken': 42}),
    ({'progressToken': True}, None),
    ({'progressToken': False}, None),
    ({'progressToken': None}, None),
    ({'progressToken': 1.5}, None),
    ({'progressToken': []}, None),
    ({'progressToken': {}}, None),
])
@pytest.mark.parametrize('accepted', [True, False])
def test_only_valid_transport_token_is_forwarded(solar_env, monkeypatch, meta, expected, accepted):
    effects = []
    monkeypatch.setitem(operations.HANDLERS, 'task.create', lambda args: effects.append(args) or {'ok': True})
    reply = {'action': 'accept', 'content': {'approve': True}} if accepted else {'action': 'cancel'}
    forms, responses = transport([execute(2, meta)], reply)
    assert len(forms) == 1
    if expected is None:
        assert '_meta' not in forms[0]['params']
    else:
        assert forms[0]['params']['_meta'] == expected
    assert forms[0]['params']['requestedSchema']['properties']['approve']['default'] is False
    result = next(item['result'] for item in responses if item.get('id') == 2)
    assert result['isError'] is not accepted
    assert len(effects) == int(accepted)
    approvals = mcp_approve.listing()
    assert len(approvals) == int(accepted)
    if accepted:
        assert approvals[0]['consumed_at']


def test_deferred_calls_keep_their_own_token_without_leaking(solar_env, monkeypatch):
    effects = []
    monkeypatch.setitem(operations.HANDLERS, 'task.create', lambda args: effects.append(args) or {'ok': True})
    messages = [execute(2, {'progressToken': 'first'}), execute(3, {'progressToken': 'second'}),
                execute(4, {})]
    forms, _ = transport(messages, {'action': 'accept', 'content': {'approve': True}})
    assert [form['params'].get('_meta') for form in forms] == [
        {'progressToken': 'first'}, {'progressToken': 'second'}, None]
    assert len({form['id'] for form in forms}) == 3
    assert [args['title'] for args in effects] == ['Fixture 2', 'Fixture 3', 'Fixture 4']
    assert len(mcp_approve.listing()) == 3


def test_tool_arguments_cannot_supply_routing_or_approval(solar_env):
    message = execute(2, None)
    message['params']['arguments']['progressToken'] = 'forged'
    response = mcp_server.handle(message, lambda *args: pytest.fail('Invalid arguments prompted'))
    assert response['error']['code'] == -32602
    assert not mcp_approve.listing()
