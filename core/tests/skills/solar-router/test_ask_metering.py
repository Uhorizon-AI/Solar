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
    stub.write_text('#!'+sys.executable+'\nimport sys,json,time\n'
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
@pytest.mark.parametrize('capture_failure', ['none', 'observation', 'finish', 'timeout', 'oversized', 'io', 'oversized_observation'])
def test_router_to_durable_console_projection_with_actual_pipe(isolated_runtime, tmp_path, monkeypatch, fails, capture_failure):
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
    if capture_failure == 'oversized_observation':
        events.insert(0, {'type':'turn.started','usage':{'input_tokens':3}})
        events[-1]['usage']['oversized_measurement'] = {
            str(i): {str(j):j for j in range(128)} for i in range(128)}
    stub.write_text('#!'+sys.executable+'\nimport sys,json,time\n'
                    'if "--version" in sys.argv: print("fixture-1");sys.exit()\n'+
                    ('print("malformed",flush=True)\n' if capture_failure == 'timeout' else '')+
                    ('print(json.dumps({"type":"tool_result","text":"x"*(2*1024*1024)}),flush=True)\n' if capture_failure == 'oversized' else '')+
                    'for x in '+repr(events)+': print(json.dumps(x),flush=True)\n'+
                    ('time.sleep(5)\n' if capture_failure == 'timeout' else '')+
                    'sys.exit('+str(int(fails))+')\n')
    stub.chmod(0o700)
    monkeypatch.setattr(PROVIDERS['codex'],'resolve_binary',lambda _:str(stub))
    payload=dict(request_id='meter-fixture',text='not injected',channel='async-task',mode='direct_only',
                 provider='codex',execution=dict(task_id=task,token=token,profile='ask_readonly_v1'))
    if capture_failure == 'timeout':
        monkeypatch.setenv('SOLAR_ROUTER_TIMEOUT_SEC', '1')
    if capture_failure in ('observation', 'io'):
        original = st.Session.token_observe
        def write_then_fail(self, *args, **kwargs):
            original(self, *args, **kwargs)
            if capture_failure == 'observation':
                raise st.FormatError('token_observation_too_large')
            import sqlite3
            raise sqlite3.OperationalError('fixture unavailable')
        monkeypatch.setattr(st.Session, 'token_observe', write_then_fail)
    elif capture_failure == 'finish':
        import sqlite3
        def finish_unavailable(*args, **kwargs):
            raise sqlite3.OperationalError('fixture busy')
        monkeypatch.setattr(st.Session, 'token_attempt_finish', finish_unavailable)
    result=router.route(json.dumps(payload))
    failed = fails or capture_failure in ('io', 'timeout')
    assert result['status']==('failed' if failed else 'success'),result
    assert not result.get('claim_released')
    if not failed:
        assert result['reply_text']=='SOLAR-METER-OK'
    with st.read_session() as store:
        usage=runtime_views.console_task_detail(store,task)['token_usage']
        a=usage['attempts'][0]
        assert store.reservation_for(task) is not None
        assert a['status']==('running' if capture_failure == 'finish' else 'timeout' if capture_failure == 'timeout' else 'failed' if failed else 'success')
        if capture_failure == 'timeout':
            assert a['capture_error'] == 'malformed_event'
        if capture_failure == 'finish':
            assert a['reason'] == 'unfinished'
        if capture_failure == 'oversized':
            assert a['capture_error'] == 'event_too_large'
        if capture_failure in ('observation', 'oversized_observation'):
            assert a['capture_error'] == 'observation_rejected'
        if failed or capture_failure in ('finish', 'observation', 'oversized', 'oversized_observation'):
            assert not usage['subtotals']
            assert all(v is None for v in a['metrics'].values())
        assert a['observations'][0]['original']['usage']['input_tokens']==(3 if capture_failure == 'oversized_observation' else 5 if fails else 0)
        assert token not in json.dumps(usage)
        incomplete = failed or capture_failure in ('finish', 'observation', 'oversized', 'oversized_observation')
        assert a['coverage']==('partial' if incomplete else 'available')
        assert usage['coverage']['input_tokens']['available'] == int(not incomplete)


def test_final_record_without_newline_and_recoverable_codex_error(tmp_path):
    events = [{'type':'error','message':'reconnecting'},
              {'type':'item.completed','item':{'type':'agent_message','text':'FINAL'}},
              {'type':'turn.completed','usage':{'input_tokens':1}}]
    cmd = process(tmp_path, 'sys.stdout.write("\\n".join(json.dumps(e) for e in '+repr(events)+'));sys.stdout.flush()\n')
    receiver = Observer()
    assert run('codex',cmd,cwd=tmp_path,env=None,timeout=2,observer=receiver) == 'FINAL'
    assert receiver.events[-1][1]['terminal'] and receiver.problem is None


def test_oversized_tool_event_is_discarded_without_losing_final_answer(tmp_path):
    cmd = process(tmp_path, 'print(json.dumps({"type":"tool_result","text":"x"*(2*1024*1024)}),flush=True)\n'
                  'print(json.dumps({"type":"result","subtype":"success","result":"FINAL","usage":{"input_tokens":2}}),flush=True)\n')
    receiver = Observer()
    assert run('claude',cmd,cwd=tmp_path,env=None,timeout=3,observer=receiver) == 'FINAL'
    assert receiver.problem == 'event_too_large'
    assert receiver.events[-1][1]['usage']['input_tokens'] == 2


def test_multimodel_terminal_does_not_inherit_intermediate_model(tmp_path):
    events = [{'type':'assistant','message':{'model':'model-a','usage':{'input_tokens':1}}},
              {'type':'result','subtype':'success','result':'FINAL','usage':{'input_tokens':20},
               'modelUsage':{'model-a':{'inputTokens':10},'model-b':{'inputTokens':10}}}]
    cmd = process(tmp_path,'for e in '+repr(events)+': print(json.dumps(e),flush=True)\n')
    receiver = Observer()
    assert run('claude',cmd,cwd=tmp_path,env=None,timeout=3,observer=receiver) == 'FINAL'
    assert not receiver.events[-1][1].get('model')


def test_version_probe_failure_does_not_lose_answer(tmp_path):
    stub = tmp_path/'client'
    stub.write_text('#!'+sys.executable+'\nimport sys,json\n'
        'if "--version" in sys.argv: print("untrusted failed version");sys.exit(3)\n'
        'print(json.dumps({"type":"result","subtype":"success","result":"FINAL","usage":{"input_tokens":0}}))\n')
    stub.chmod(0o700)
    receiver = Observer()
    assert run('claude',[str(stub)],cwd=tmp_path,env=None,timeout=3,observer=receiver) == 'FINAL'
    assert receiver.launch[1] is None


def test_aggregate_without_breakdown_does_not_inherit_one_of_multiple_models(tmp_path):
    events = [{'type':'assistant','message':{'model':m,'usage':{'input_tokens':1}}} for m in ['model-a','model-b']]
    events.append({'type':'result','subtype':'success','result':'FINAL','usage':{'input_tokens':20}})
    receiver = Observer()
    cmd = process(tmp_path,'for e in '+repr(events)+': print(json.dumps(e),flush=True)\n')
    assert run('claude',cmd,cwd=tmp_path,env=None,timeout=3,observer=receiver) == 'FINAL'
    assert not receiver.events[-1][1].get('model')


@pytest.mark.parametrize('failed_usage', [None, {'input_tokens':7,'output_tokens':1}])
@pytest.mark.parametrize('completed_first', [False, True])
def test_codex_failed_terminal_survives_transport_and_prevents_ambiguous_metrics(tmp_path, failed_usage, completed_first):
    from token_usage import project
    failed = {'type':'turn.failed','error':{'message':'synthetic failure'}}
    if failed_usage is not None:
        failed['usage'] = failed_usage
    events = ([{'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]
              if completed_first else []) + [failed]
    receiver = Observer()
    cmd = process(tmp_path,'for e in '+repr(events)+': print(json.dumps(e),flush=True)\n')
    with pytest.raises(RuntimeError):
        run('codex',cmd,cwd=tmp_path,env=None,timeout=3,observer=receiver)
    terminal = receiver.events[-1][1]
    assert terminal['event_type'] == 'turn.failed'
    assert terminal['terminal'] is True and terminal['successful'] is False
    assert ('usage' in terminal) == (failed_usage is not None)
    attempt = dict(id='fixture',provider='codex',status='failed',finished_at='done',
                   capture_error=None,cli_version='fixture',
                   observations=[{'original':o} for _,o in receiver.events])
    data = project([attempt])
    assert all(value is None for value in data['attempts'][0]['metrics'].values())
    assert not data['subtotals']
    if completed_first:
        assert data['attempts'][0]['reason'] == 'ambiguous_terminals'
        assert data['attempts'][0]['coverage'] == 'partial'
    else:
        assert data['attempts'][0]['reason'] == 'failed'
        assert data['attempts'][0]['coverage'] == ('partial' if failed_usage is not None else 'not_available')


@pytest.mark.parametrize('provider', ['codex', 'claude', 'agent', 'agy'])
@pytest.mark.parametrize('newline', [True, False])
def test_large_final_answer_is_preserved_and_measurement_still_selected(tmp_path, monkeypatch, provider, newline):
    # Generate the answer inside the child, not as an oversized OS command argument.
    import ask_metering
    original = ask_metering.tempfile.TemporaryFile
    files = []
    def tracked_file(*args, **kwargs):
        stream = original(*args, **kwargs)
        files.append(stream)
        return stream
    monkeypatch.setattr(ask_metering.tempfile, 'TemporaryFile', tracked_file)
    if provider == 'codex':
        body = 'events=[{"type":"item.completed","item":{"type":"agent_message","text":answer}},{"type":"turn.completed","usage":{"input_tokens":2}}]\n'
    elif provider == 'agy':
        body = 'events=[{"event":"result","result":{"status":"SUCCESS","response":answer,"usage":{"input_tokens":2}}}]\n'
    else:
        body = 'events=[{"type":"result","subtype":"success","result":answer,"usage":{"input_tokens":2}}]\n'
    body = 'answer="x"*(2*1024*1024)+"FINAL"\n'+body
    body += 'sys.stdout.write("\\n".join(json.dumps(e) for e in events)'+(' + "\\n"' if newline else '')+');sys.stdout.flush()\n'
    receiver = Observer()
    result = run(provider,process(tmp_path,body),cwd=tmp_path,env=None,timeout=4,observer=receiver)
    assert len(result) == 2*1024*1024+5 and result.endswith('FINAL')
    assert files and all(stream.closed for stream in files)
    assert receiver.problem is None
    assert receiver.events[-1][1]['usage']['input_tokens'] == 2


@pytest.mark.parametrize('provider', ['claude', 'codex', 'agent', 'agy'])
def test_repository_review_route_leaves_a_metered_attempt_in_the_console(isolated_runtime, tmp_path, monkeypatch, provider):
    """The route meters every profile: a review ends with Entrada/Salida, not with no attempt at all."""
    import router
    import solar_state as st
    import runtime_views
    import repository_reviews as repo
    from ask_metering import review_observation
    from git_review_fixture import repository
    from reservation_tokens import token_of
    root, commit = repository(tmp_path)
    built = repo.build(repository=str(root), commit=commit, provider=provider, model=None,
                       instructions='Review.', rules=['Cite sources.'])
    with st.session() as store:
        fields = [('title', json.dumps('Review meter')), ('provider', json.dumps(provider)),
                  ('access_policy', json.dumps(dict(version=1, mode='read', scopes=[str(root)], resources=[]))),
                  ('execution_profile', json.dumps(repo.PROFILE)),
                  ('review_input_manifest', json.dumps(built['manifest'])),
                  ('review_input_digest', json.dumps(built['review_input_digest']))]
        task = store.task_create(fields, '\n# Review meter\n\nReview.\n')
        store.task_approve(task, expected_row_version=store.task_get(task)['row_version'])
        assert store.task_claim_detail(task, 'test-worker')['claimed']
        token = token_of(store, task)
    adapter = PROVIDERS[provider]

    def fake_review(*, observation_sink=None, **kwargs):
        assert observation_sink is not None, 'a restricted profile reached the provider unmetered'
        observation_sink.launched(provider, None)
        usage = dict(input_tokens=21, output_tokens=8)
        observation_sink(1, review_observation(provider, {}, usage))
        return 'Review text'
    monkeypatch.setattr(adapter, 'run_review', fake_review)
    result = router.route(json.dumps(dict(request_id='review-meter', text='x', channel='async-task', mode='direct_only',
                                          provider=provider, execution=dict(task_id=task, token=token, profile=repo.PROFILE))))
    assert result['status'] == 'success', result
    with st.read_session() as store:
        usage = runtime_views.console_task_detail(store, task)['token_usage']
        attempt = usage['attempts'][0]
        assert attempt['status'] == 'success' and attempt['coverage'] == 'available'
        assert attempt['metrics']['input_tokens'] == 21 and attempt['metrics']['output_tokens'] == 8
        row = next(r for r in runtime_views.console_tasks(store)['tasks'] if r['id'] == task)
        assert row['token_groups'][0]['metrics']['input_tokens']['subtotal'] == 21


def test_provider_failure_in_a_review_is_a_failed_attempt_not_a_missing_one(isolated_runtime, tmp_path, monkeypatch):
    import router
    import solar_state as st
    import repository_reviews as repo
    from git_review_fixture import repository
    from reservation_tokens import token_of
    root, commit = repository(tmp_path)
    built = repo.build(repository=str(root), commit=commit, provider='claude', model=None,
                       instructions='Review.', rules=['Cite sources.'])
    with st.session() as store:
        fields = [('title', json.dumps('Review failure')), ('provider', json.dumps('claude')),
                  ('access_policy', json.dumps(dict(version=1, mode='read', scopes=[str(root)], resources=[]))),
                  ('execution_profile', json.dumps(repo.PROFILE)),
                  ('review_input_manifest', json.dumps(built['manifest'])),
                  ('review_input_digest', json.dumps(built['review_input_digest']))]
        task = store.task_create(fields, '\n# Review failure\n\nReview.\n')
        store.task_approve(task, expected_row_version=store.task_get(task)['row_version'])
        assert store.task_claim_detail(task, 'test-worker')['claimed']
        token = token_of(store, task)

    def broken(*, observation_sink=None, **kwargs):
        observation_sink.launched('claude', None)
        raise RuntimeError('provider exploded')
    monkeypatch.setattr(PROVIDERS['claude'], 'run_review', broken)
    result = router.route(json.dumps(dict(request_id='review-failure', text='x', channel='async-task', mode='direct_only',
                                          provider='claude', execution=dict(task_id=task, token=token, profile=repo.PROFILE))))
    assert result['status'] == 'failed'
    with st.read_session() as store:
        [attempt] = store.task_token_usage(task)['attempts']
        assert attempt['status'] == 'failed' and attempt['reason'] == 'failed'
        assert attempt['coverage'] == 'not_available'


@pytest.mark.parametrize('provider,stdout,expected', [
    ('agent', {'type': 'result', 'subtype': 'success', 'result': 'ok', 'usage': {'inputTokens': 21}}, {'inputTokens': 21}),
    ('agent', {'type': 'result', 'subtype': 'success', 'result': 'ok',
               'usage': {'inputTokens': 21, 'outputTokens': 8, 'cacheWriteTokens': 5, 'future_counter': 7}},
     {'inputTokens': 21, 'outputTokens': 8, 'cacheWriteTokens': 5, 'future_counter': 7}),
    ('claude', {'result': 'ok', 'usage': {'input_tokens': 3, 'output_tokens': 0}, 'total_cost_usd': 0.5, 'session_id': 's1'},
     {'input_tokens': 3, 'output_tokens': 0}),
    ('agy', {'status': 'SUCCESS', 'response': 'ok', 'usage': {'input_tokens': 1, 'output_tokens': 2}}, {'input_tokens': 1, 'output_tokens': 2}),
    ('claude', {'result': 'ok'}, None),
])
def test_review_records_the_clients_native_counters_without_inventing_zeros(monkeypatch, provider, stdout, expected):
    import contextlib
    import subprocess

    @contextlib.contextmanager
    def launch(*a, **k):
        yield [provider, '--x'], {}, '.'
    monkeypatch.setattr(ep, 'restricted_launch', launch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: type('R', (), {'returncode': 0, 'stdout': json.dumps(stdout), 'stderr': ''})())
    adapter = PROVIDERS[provider]
    monkeypatch.setattr(adapter, 'last_review_preflight', {'version': '9.9.9'}, raising=False)
    receiver = Observer()
    out = adapter.run_review(manifest={}, expected='', profile='other_profile_v1', observation_sink=receiver)
    assert out == 'ok'
    assert receiver.launch == (provider, '9.9.9')
    [(position, observation)] = receiver.events
    assert position == 1 and observation['terminal'] and observation['successful']
    assert observation.get('usage') == expected
