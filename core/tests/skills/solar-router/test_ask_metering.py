"""Real pipe transport with fake local processes; no model, auth or live runtime."""
import json
import sys
import time
from pathlib import Path

import pytest
from ask_metering import run, selection, output_flags
from providers import PROVIDERS
import execution_profiles as ep


class Observer:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail
        self.problem = None
        self.launch = None

    def launched(self, binary, version):
        self.launch = (binary, version)

    def __call__(self, position, observation):
        if self.fail:
            raise RuntimeError('persist_failed')
        self.events.append((position, observation))

    def capture_problem(self, problem):
        self.problem = problem


@pytest.mark.parametrize('provider,event', [
    ('codex', {'type':'turn.completed','usage':{'input_tokens':16417,'cached_input_tokens':13184,'cache_write_input_tokens':0,'output_tokens':10}}),
    ('claude', {'type':'result','subtype':'success','result':'SOLAR-METER-OK','usage':{'input_tokens':2,'cache_creation_input_tokens':3782,'cache_read_input_tokens':649,'output_tokens':13}}),
    ('agent', {'type':'result','subtype':'success','result':'SOLAR-METER-OK','usage':{'inputTokens':8397,'outputTokens':108,'cacheReadTokens':3968,'cacheWriteTokens':0}}),
    ('agy', {'event':'result','result':{'status':'SUCCESS','response':'SOLAR-METER-OK','usage':{'input_tokens':1,'output_tokens':2}}}),
])
def test_native_shapes_preserve_zero_and_return_text_under_original_permissions(tmp_path, monkeypatch, provider, event):
    # CLI stub accepts Solar's real argv and emits only fixture events.
    events = [event]
    if provider == 'codex':
        events.insert(0, {'type':'item.completed','item':{'type':'agent_message','text':'SOLAR-METER-OK'}})
    stub = tmp_path/'client'
    stub.write_text('#!'+sys.executable+'\nimport sys,json\n'
                    'if "--version" in sys.argv: print("fixture-1");sys.exit()\n'
                    'for x in '+repr(events)+': print(json.dumps(x),flush=True)\n')
    stub.chmod(0o700)
    adapter = PROVIDERS[provider]
    monkeypatch.setattr(adapter, 'resolve_binary', lambda _: str(stub))
    monkeypatch.setenv('SOLAR_ROUTER_TIMEOUT_SEC', '3')
    receiver = Observer()
    answer = adapter.ask('do not use tools', cwd=tmp_path, observer=receiver)
    assert answer.text == 'SOLAR-METER-OK'
    assert receiver.launch == (str(stub), 'fixture-1')
    assert receiver.events[0][1]['usage'] == (event.get('usage') or event['result']['usage'])
    assert receiver.events[0][1]['successful']
    assert '--json' in output_flags('codex')


def process(tmp_path, body):
    path=tmp_path/'stub.py'
    path.write_text('import sys,time,json\nif "--version" in sys.argv: print("1");sys.exit()\n'+body)
    return [sys.executable, str(path)]


def test_observations_arrive_before_timeout_even_when_stderr_pipe_fills(tmp_path, monkeypatch):
    # Use sys.executable stub directly; version helper prints Python's version harmlessly.
    cmd=process(tmp_path, 'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":7}}),flush=True)\nsys.stderr.write("x"*200000);sys.stderr.flush()\ntime.sleep(5)\n')
    receiver=Observer()
    start=time.monotonic()
    with pytest.raises(TimeoutError):
        run('codex',cmd,cwd=tmp_path,env=None,timeout=.4,observer=receiver)
    assert time.monotonic()-start < 3
    assert receiver.events[0][1]['usage']['input_tokens']==7


def test_persistence_failure_stops_transport_without_claiming_success(tmp_path):
    cmd=process(tmp_path, 'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":7}}),flush=True)\ntime.sleep(5)\n')
    with pytest.raises(RuntimeError,match='persist_failed'):
        run('codex',cmd,cwd=tmp_path,env=None,timeout=2,observer=Observer(fail=True))


def test_failure_keeps_received_usage_and_missing_final_is_an_error(tmp_path):
    cmd=process(tmp_path, 'print(json.dumps({"type":"assistant","message":{"usage":{"input_tokens":2}}}),flush=True)\nsys.exit(1)\n')
    receiver=Observer()
    with pytest.raises(RuntimeError):
        run('claude',cmd,cwd=tmp_path,env=None,timeout=2,observer=receiver)
    assert receiver.events
    assert not receiver.events[0][1]['terminal']


def test_metadata_only_and_unknown_fields_are_not_reply_text():
    obs=selection('agent',{'type':'result','subtype':'success','result':'PRIVATE','usage':{'inputTokens':0}})
    assert 'PRIVATE' not in json.dumps(obs)


@pytest.mark.parametrize('fails', [False, True])
def test_router_to_durable_console_projection_with_actual_pipe(isolated_runtime, tmp_path, monkeypatch, fails):
    import router
    import solar_state as st
    import runtime_views
    from reservation_tokens import token_of
    workspace = isolated_runtime.workspace
    built = ep.build_ask_envelope(provider='codex', prompt='Return marker', cwd=str(workspace), model=None)
    with st.session() as store:
        fields = [('title', json.dumps('Meter integration')), ('provider', json.dumps('codex')),
                  ('access_policy', json.dumps(dict(version=1,mode='read',scopes=[str(workspace)],resources=[]))),
                  ('execution_profile', json.dumps('ask_readonly_v1')),
                  ('review_input_manifest', json.dumps(built['manifest'])),
                  ('review_input_digest', json.dumps(built['review_input_digest']))]
        task = store.task_create(fields, '\n# Meter integration\n\nReturn marker.\n')
        store.task_approve(task, expected_row_version=store.task_get(task)['row_version'])
        assert store.task_claim_detail(task,'test-worker')['claimed']
        token = token_of(store, task)
    stub=tmp_path/'meter-client'
    events = ([{'type':'assistant','message':{'usage':{'input_tokens':5}}}] if fails else [
        {'type':'item.completed','item':{'type':'agent_message','text':'SOLAR-METER-OK'}},
        {'type':'turn.completed','usage':{'input_tokens':0,'output_tokens':10}}])
    # Failure case emits a native Codex terminal counter before exiting nonzero.
    if fails:
        events=[{'type':'turn.completed','usage':{'input_tokens':5,'output_tokens':2}}]
    stub.write_text('#!'+sys.executable+'\nimport sys,json\n'
                    'if "--version" in sys.argv: print("fixture-1");sys.exit()\n'
                    'for x in '+repr(events)+': print(json.dumps(x),flush=True)\n'
                    'sys.exit('+str(int(fails))+')\n')
    stub.chmod(0o700)
    monkeypatch.setattr(PROVIDERS['codex'],'resolve_binary',lambda _:str(stub))
    payload=dict(request_id='meter-fixture',text='not injected',channel='async-task',mode='direct_only',
                 provider='codex',execution=dict(task_id=task,token=token,profile='ask_readonly_v1'))
    result=router.route(json.dumps(payload))
    assert result['status']==('failed' if fails else 'success'),result
    if not fails:
        assert result['reply_text']=='SOLAR-METER-OK'
    with st.read_session() as store:
        usage=runtime_views.console_task_detail(store,task)['token_usage']
        a=usage['attempts'][0]
        assert a['status']==('failed' if fails else 'success')
        assert a['observations'][0]['original']['usage']['input_tokens']==(5 if fails else 0)
        assert token not in json.dumps(usage)
        assert a['coverage']==('partial' if fails else 'available')
