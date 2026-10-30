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
@pytest.mark.parametrize('profile', ['repository_readonly_v1', 'text_only_review_v1'])
def test_review_records_the_clients_native_counters_without_inventing_zeros(monkeypatch, provider, stdout, expected, profile):
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
    if profile == 'repository_readonly_v1':
        monkeypatch.setattr(ep, 'verify_envelope', lambda *a, **k: {'user_prompt': json.dumps({'commit': 'c', 'repository': '.'})})
    out = adapter.run_review(manifest={}, expected='', profile=profile, observation_sink=receiver)
    assert out.endswith('ok')
    assert receiver.launch == (provider, '9.9.9')
    [(position, observation)] = receiver.events
    assert position == 1 and observation['terminal'] and observation['successful']
    assert observation.get('usage') == expected


# --- Restricted executions through the real adapter: failure, timeout, stream, no sink ---------------------

def _review_task(tmp_path, provider='claude'):
    import solar_state as st
    import repository_reviews as repo
    from git_review_fixture import repository
    from reservation_tokens import token_of
    root, commit = repository(tmp_path)
    built = repo.build(repository=str(root), commit=commit, provider=provider, model=None,
                       instructions='Review.', rules=['Cite sources.'])
    with st.session() as store:
        fields = [('title', json.dumps('Review real adapter')), ('provider', json.dumps(provider)),
                  ('access_policy', json.dumps(dict(version=1, mode='read', scopes=[str(root)], resources=[]))),
                  ('execution_profile', json.dumps(repo.PROFILE)),
                  ('review_input_manifest', json.dumps(built['manifest'])),
                  ('review_input_digest', json.dumps(built['review_input_digest']))]
        task = store.task_create(fields, '\n# Review real adapter\n\nReview.\n')
        store.task_approve(task, expected_row_version=store.task_get(task)['row_version'])
        assert store.task_claim_detail(task, 'test-worker')['claimed']
        return task, token_of(store, task), repo.PROFILE


def _real_adapter(monkeypatch, tmp_path, provider, run):
    """The real run_review, with only the process launch replaced: the meter is wired by the adapter itself."""
    import contextlib
    import types
    import subprocess
    from providers import base
    last = tmp_path / 'last-message.json'
    last.write_text(json.dumps({'review': 'Review text'}))

    @contextlib.contextmanager
    def launch(*a, **k):
        yield [provider, '--output-last-message', str(last)], {}, str(tmp_path)
    monkeypatch.setattr(ep, 'restricted_launch', launch)
    monkeypatch.setattr(base, 'subprocess', types.SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(PROVIDERS[provider], 'last_review_preflight', {'version': '1.2.3'}, raising=False)


def _completed(stdout):
    return lambda *a, **k: type('R', (), {'returncode': 0, 'stdout': stdout, 'stderr': ''})()


def _route(task, token, profile, provider, stream=False):
    import router
    raw = json.dumps(dict(request_id='real-adapter', text='x', channel='async-task', mode='direct_only',
                          provider=provider, execution=dict(task_id=task, token=token, profile=profile)))
    if stream:
        return [json.loads(line) for line in router.route_stream(raw)]
    return router.route(raw)


STDOUT = {
    'claude': json.dumps({'result': 'Review text', 'usage': {'input_tokens': 21, 'output_tokens': 8}}),
    'codex': '\n'.join(json.dumps(e) for e in [
        {'type': 'item.completed'}, {'type': 'turn.completed', 'usage': {'input_tokens': 21, 'output_tokens': 8}}]),
    'agent': json.dumps({'type': 'result', 'subtype': 'success', 'result': 'Review text',
                         'usage': {'inputTokens': 21, 'outputTokens': 8}}),
    'agy': json.dumps({'status': 'SUCCESS', 'response': 'Review text', 'usage': {'input_tokens': 21, 'output_tokens': 8}}),
}


@pytest.mark.parametrize('provider', ['claude', 'codex', 'agent', 'agy'])
@pytest.mark.parametrize('stream', [False, True])
def test_real_adapter_leaves_one_metered_attempt_per_provider_and_transport(isolated_runtime, tmp_path, monkeypatch, provider, stream):
    import solar_state as st
    task, token, profile = _review_task(tmp_path, provider)
    _real_adapter(monkeypatch, tmp_path, provider, _completed(STDOUT[provider]))
    result = _route(task, token, profile, provider, stream=stream)
    assert (result[-1] if stream else result)['status'] == 'success'
    with st.read_session() as store:
        [attempt] = store.task_token_usage(task)['attempts']
        assert attempt['status'] == 'success' and attempt['coverage'] == 'available'
        assert attempt['launch_confirmed'] is True
        assert len(attempt['observations']) == 1
        assert attempt['metrics']['output_tokens'] == 8


@pytest.mark.parametrize('provider', ['claude', 'codex', 'agent', 'agy'])
def test_real_adapter_timeout_is_a_timed_out_attempt_that_was_launched(isolated_runtime, tmp_path, monkeypatch, provider):
    import subprocess
    import solar_state as st
    task, token, profile = _review_task(tmp_path, provider)

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd=provider, timeout=1)
    _real_adapter(monkeypatch, tmp_path, provider, slow)
    assert _route(task, token, profile, provider)['status'] == 'failed'
    with st.read_session() as store:
        usage = store.task_token_usage(task)
        [attempt] = usage['attempts']
        assert attempt['status'] == 'timeout' and attempt['reason'] == 'cli_timeout'
        assert attempt['coverage'] == 'not_available' and attempt['launch_confirmed'] is True


@pytest.mark.parametrize('provider', ['claude', 'codex', 'agent', 'agy'])
@pytest.mark.parametrize('error', [FileNotFoundError, PermissionError])
def test_real_adapter_exec_failure_is_not_a_launched_attempt(isolated_runtime, tmp_path, monkeypatch, error, provider):
    import solar_state as st
    task, token, profile = _review_task(tmp_path, provider)

    def broken(*a, **k):
        raise error('no client')
    _real_adapter(monkeypatch, tmp_path, provider, broken)
    assert _route(task, token, profile, provider)['status'] == 'failed'
    with st.read_session() as store:
        usage = store.task_token_usage(task)
        [attempt] = usage['attempts']
        assert attempt['status'] == 'not_launched' and attempt['coverage'] == 'not_available'
        assert usage['coverage']['input_tokens']['launched'] == 0


@pytest.mark.parametrize('provider,stdout,returncode', [
    ('claude', json.dumps({'is_error': True, 'result': 'quota', 'usage': {'input_tokens': 5, 'output_tokens': 1}}), 0),
    ('claude', json.dumps({'result': '', 'usage': {'input_tokens': 5, 'output_tokens': 1}}), 0),
    ('claude', json.dumps({'result': 'x', 'usage': {'input_tokens': 5, 'output_tokens': 1}}), 1),
    ('agent', json.dumps({'type': 'result', 'subtype': 'error', 'usage': {'inputTokens': 5, 'outputTokens': 1}}), 0),
    ('codex', '\n'.join(json.dumps(e) for e in [{'type': 'turn.failed', 'usage': {'input_tokens': 5, 'output_tokens': 1}}]), 0),
    ('codex', '\n'.join([json.dumps({'type': 'turn.failed', 'usage': {'input_tokens': 5, 'output_tokens': 1}}), '{"type": "tur']), 0),
    ('agy', json.dumps({'status': 'ERROR', 'usage': {'input_tokens': 5, 'output_tokens': 1}}), 0),
    ('agy', json.dumps({'status': 'SUCCESS', 'response': 'x', 'usage': {'input_tokens': 5, 'output_tokens': 1}}), 2),
    ('agent', json.dumps({'type': 'result', 'subtype': 'success', 'result': 'x', 'usage': {'inputTokens': 5, 'outputTokens': 1}}), 1),
])
def test_rejected_reply_keeps_its_counters_as_partial_evidence_not_metrics(isolated_runtime, tmp_path, monkeypatch, provider, stdout, returncode):
    import solar_state as st
    task, token, profile = _review_task(tmp_path, provider)
    _real_adapter(monkeypatch, tmp_path, provider,
                  lambda *a, **k: type('R', (), {'returncode': returncode, 'stdout': stdout, 'stderr': ''})())
    assert _route(task, token, profile, provider)['status'] == 'failed'
    with st.read_session() as store:
        [attempt] = store.task_token_usage(task)['attempts']
        assert attempt['status'] == 'failed' and attempt['coverage'] == 'partial'
        [observation] = attempt['observations']  # one record, never the success path as well
        assert observation['original']['successful'] is False and observation['original']['terminal']
        assert all(v is None for v in attempt['metrics'].values())  # evidence, never a validated subtotal
        assert store.task_token_usage(task)['subtotals'] == []


def test_review_without_a_sink_still_returns_its_text(monkeypatch, tmp_path):
    _real_adapter(monkeypatch, tmp_path, 'claude', _completed(STDOUT['claude']))
    monkeypatch.setattr(ep, 'verify_envelope', lambda *a, **k: {'user_prompt': json.dumps({'commit': 'c', 'repository': '.'})})
    out = PROVIDERS['claude'].run_review(manifest={}, expected='', profile='text_only_review_v1')
    assert out == 'Review text'


def test_agy_keeps_session_and_cost_from_the_original_record(monkeypatch, tmp_path):
    record = {'status': 'SUCCESS', 'response': 'ok', 'usage': {'input_tokens': 1, 'output_tokens': 2},
              'session_id': 's-agy', 'total_cost_usd': 0.25}
    _real_adapter(monkeypatch, tmp_path, 'agy', _completed(json.dumps(record)))
    receiver = Observer()
    PROVIDERS['agy'].run_review(manifest={}, expected='', profile='text_only_review_v1', observation_sink=receiver)
    [(_, observation)] = receiver.events
    assert observation['session_id'] == 's-agy' and observation['reported_estimate_usd'] == 0.25


def _end_rows():
    import solar_state as st
    with st.read_session() as store:
        return store.audit_rows(event='end')


@pytest.mark.parametrize('streaming', [False, True])
def test_interactive_replies_say_in_the_audit_that_they_are_not_measurable(isolated_runtime, tmp_path, monkeypatch, streaming):
    import router
    raw = json.dumps(dict(request_id='i', session_id='s', user_id='u', text='hello', channel='other', mode='direct_only'))
    reply = ('ok', 'claude')
    monkeypatch.setattr(router, 'run_with_fallback', lambda prompt: reply)
    monkeypatch.setattr(router, 'stream_provider', lambda prompt, provider_override=None: iter([reply]))
    list(router.route_stream(raw)) if streaming else router.route(raw)
    monkeypatch.setattr(router, 'run_with_fallback', lambda prompt: (_ for _ in ()).throw(RuntimeError('dead')))
    router.route(raw)  # the failed interactive reply has no task identity either
    ends = _end_rows()
    assert len(ends) == 2 and all(r['token_measurement'] == 'not_measurable' for r in ends)
    assert all(r['token_measurement_reason'] == 'interactive_route_no_task' for r in ends)


def test_task_bound_executions_do_not_claim_to_be_unmeasurable(isolated_runtime, tmp_path, monkeypatch):
    task, token, profile = _review_task(tmp_path)
    _real_adapter(monkeypatch, tmp_path, 'claude', _completed(STDOUT['claude']))
    assert _route(task, token, profile, 'claude')['status'] == 'success'
    [end] = _end_rows()
    assert 'token_measurement' not in end


def test_a_codex_rejection_is_labelled_as_a_failed_turn(monkeypatch, tmp_path):
    stdout = json.dumps({'type': 'turn.failed', 'usage': {'input_tokens': 5, 'output_tokens': 1}})
    _real_adapter(monkeypatch, tmp_path, 'codex', _completed(stdout))
    receiver = Observer()
    with pytest.raises(RuntimeError):
        PROVIDERS['codex'].run_review(manifest={}, expected='', profile='text_only_review_v1', observation_sink=receiver)
    [(_, observation)] = receiver.events
    assert observation['event_type'] == 'turn.failed' and observation['successful'] is False


class _BrokenMeter(Observer):
    def launched(self, binary, version):
        self.capture_problem('persistence_failed')
        raise RuntimeError('persist_failed')


def test_a_meter_that_cannot_persist_the_launch_never_replaces_the_review_outcome(monkeypatch, tmp_path):
    import subprocess
    _real_adapter(monkeypatch, tmp_path, 'claude', _completed(STDOUT['claude']))
    meter = _BrokenMeter()
    assert PROVIDERS['claude'].run_review(manifest={}, expected='', profile='text_only_review_v1',
                                          observation_sink=meter) == 'Review text'
    assert meter.problem == 'persistence_failed'

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd='claude', timeout=1)
    _real_adapter(monkeypatch, tmp_path, 'claude', slow)
    with pytest.raises(subprocess.TimeoutExpired):  # the real outcome, not the meter's failure
        PROVIDERS['claude'].run_review(manifest={}, expected='', profile='text_only_review_v1', observation_sink=_BrokenMeter())


@pytest.mark.parametrize('error', [RuntimeError('dead'), None])
def test_failed_streamed_interactive_replies_close_their_audit_start(isolated_runtime, monkeypatch, error):
    import router
    from router import UnsupportedProviderPriorityError

    def broken(prompt, provider_override=None):
        raise error or UnsupportedProviderPriorityError('bad priority')
        yield
    monkeypatch.setattr(router, 'stream_provider', broken)
    raw = json.dumps(dict(request_id='i', session_id='s', user_id='u', text='hello', channel='other', mode='direct_only'))
    [done] = [json.loads(line) for line in router.route_stream(raw) if json.loads(line)['type'] == 'done']
    assert done['status'] == 'failed'
    [end] = _end_rows()
    assert end['status'] == 'failed' and end['stream'] is True and end['token_measurement'] == 'not_measurable'


@pytest.mark.parametrize('provider', ['claude', 'codex', 'agent', 'agy'])
@pytest.mark.parametrize('stdout', ['', 'not json at all', '\ufffd\x00 broken'])
def test_a_client_failure_without_usable_output_is_not_a_meter_failure(isolated_runtime, tmp_path, monkeypatch, provider, stdout):
    import solar_state as st
    task, token, profile = _review_task(tmp_path, provider)
    _real_adapter(monkeypatch, tmp_path, provider,
                  lambda *a, **k: type('R', (), {'returncode': 1, 'stdout': stdout, 'stderr': ''})())
    assert _route(task, token, profile, provider)['status'] == 'failed'
    with st.read_session() as store:
        [attempt] = store.task_token_usage(task)['attempts']
        assert attempt['status'] == 'failed' and attempt['observations'] == []
        assert attempt['capture_error'] is None  # said directly, not inferred from `reason`
        assert attempt['reason'] == 'failed'  # the client failed; nothing says the meter did


class _MeterThatCannotObserve(Observer):
    def __call__(self, position, observation):
        self.capture_problem('persistence_failed')
        raise RuntimeError('persist_failed')


def test_a_meter_that_cannot_persist_the_counters_never_replaces_a_paid_review(monkeypatch, tmp_path):
    _real_adapter(monkeypatch, tmp_path, 'claude', _completed(STDOUT['claude']))
    meter = _MeterThatCannotObserve()
    assert PROVIDERS['claude'].run_review(manifest={}, expected='', profile='text_only_review_v1',
                                          observation_sink=meter) == 'Review text'
    assert meter.problem == 'persistence_failed'


def test_a_meter_that_cannot_persist_rejected_counters_keeps_the_client_failure(monkeypatch, tmp_path):
    stdout = json.dumps({'is_error': True, 'result': 'quota', 'usage': {'input_tokens': 5, 'output_tokens': 1}})
    _real_adapter(monkeypatch, tmp_path, 'claude', _completed(stdout))
    meter = _MeterThatCannotObserve()
    with pytest.raises(RuntimeError, match='no review text'):  # the client's failure, not the meter's
        PROVIDERS['claude'].run_review(manifest={}, expected='', profile='text_only_review_v1', observation_sink=meter)
    assert meter.problem == 'persistence_failed'
