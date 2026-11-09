"""Approved child materialization through the real executor, with a router double."""
import json
import importlib.util
import test_subtask_worker
from pathlib import Path
import pytest
import solar_state
from review_inputs import create_parent
from queue_mirror import seed, mirror
from test_subtask_worker import make_root, run_executor, block, write_parent


def capture_router_prompt(monkeypatch):
    stub = test_subtask_worker.ROUTER_STUB.replace('sys.stdin.read()', 'packet = json.loads(sys.stdin.read())')
    stub = stub.replace('write_text("called",', 'write_text(packet["text"],')
    monkeypatch.setattr(test_subtask_worker, 'ROUTER_STUB', stub)


def test_imported_prompt_retains_author_result_without_claiming_a_verified_boundary(tmp_path):
    root = make_root(tmp_path)
    seed(root)
    with solar_state.session() as store:
        task = store.task_import('---\nid: "ambiguous-prompt"\nstatus: active\ntitle: "T"\n---\n'
                                 '\n# T\n\nRead the example.\n## Result\nAuthor example must survive.\n')
        context = store.task_definition_context(task)
    script = Path(__file__).resolve().parents[3] / 'skills/solar-async-tasks/scripts/execute_active.py'
    spec = importlib.util.spec_from_file_location('context_executor', script)
    executor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(executor)
    prompt = executor.build_prompt(task, 'T', context['instructions'],
                                   context=context['context'], boundary=context['boundary'])
    instructions, history = prompt.split('Generated execution context (non-authoritative):', 1)
    assert 'Read the example.' in instructions and 'boundary is uncertain' in instructions
    assert 'Author example must survive.' in history
    # Unknown provenance must not promote a historical Result into new authority.
    assert context['boundary'] == 'ambiguous'


@pytest.mark.parametrize('tail', ['## Result\nOld cycle.', '## Execution Error\nRetry diagnosis.'])
def test_ordinary_executor_delivers_history_as_context_not_instructions(tmp_path, monkeypatch, tail):
    root = make_root(tmp_path)
    seed(root)
    with solar_state.session() as store:
        task = store.task_create([('title', '"Context"'), ('recurring', 'true')],
                                 '\n# Context\n\nApproved work.\n')
        store.task_approve(task)
        store.task_claim_detail(task, 'test')
        store.task_set_body(task, store.task_get(task)['body'] + '\n' + tail + '\n')
    mirror(root)
    capture = tmp_path / 'prompt.txt'
    capture_router_prompt(monkeypatch)
    result = run_executor(root / 'active' / f'{task}.md', root, 'done', tmp_path, marker=capture)
    assert result.returncode == 0, result.stderr
    instructions, context = capture.read_text().split('Generated execution context (non-authoritative):', 1)
    assert 'Approved work.' in instructions and tail not in instructions
    assert tail in context and 'Definition boundary: snapshot' in instructions


def approved(root, tmp_path):
    source = tmp_path / 'evidence.txt'
    source.write_text('Evidence to review.\n')
    seed(root)
    with solar_state.session() as store:
        parent, token, declarations, catalog = create_parent(store, source)
    mirror(root)
    return source, parent, root / 'active' / f'{parent}.md', declarations


def test_approved_reviewer_declarations_remain_in_instruction_block(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _, _, path, declarations = approved(root, tmp_path)
    capture_router_prompt(monkeypatch)
    capture = tmp_path / 'declarations-prompt'
    result = run_executor(path, root, block(declarations), tmp_path, marker=capture)
    assert result.returncode == 20, result.stderr
    instructions, context = capture.read_text().split('Generated execution context (non-authoritative):', 1)
    assert 'Approved reviewer declarations' in instructions
    assert all(item["title"] in instructions and item["body"] in instructions for item in declarations)
    assert 'Approved reviewer declarations' not in context


def test_parent_three_reviews_and_one_synthesis_with_failure(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    source, parent, path, declarations = approved(root, tmp_path)
    assert run_executor(path, root, block(declarations), tmp_path).returncode == 20
    with solar_state.session() as store:
        children = store.task_field(parent, 'subtask_ids').split(',')
        ids = [entry.split('=')[1] for entry in children]
        assert len(ids) == 3
        store.task_await(parent, ids, token=store.reservation_for(parent)['token'])
        assert store.task_adopt(parent, 'test-supervisor')['released']
    mirror(root)
    for i, child in enumerate(ids):
        with solar_state.session() as store:
            claimed = store.task_claim_detail(child, 'child')
            assert claimed['claimed']
            if i == 1:
                store.task_fail(child, '## Execution Error\n- error: Known child failure\n', token=claimed['token'])
                continue
        mirror(root)
        child_path = root / 'active' / f'{child}.md'
        result = run_executor(child_path, root, '<subtasks>ignored</subtasks><delivery>ignored</delivery>Review text', tmp_path)
        assert result.returncode == 0, result.stderr
        with solar_state.session() as store:
            assert '## Delivery' not in store.task_get(child)['body']
            log = Path(store.task_get(child)['log_path']).read_text()
            assert '- usage: {\"input_tokens\": 12, \"output_tokens\": 4}' in log
            assert len(store.task_list()) == 4
            store.task_complete(child, token=store.reservation_for(child)['token'])
            assert store.task_adopt(child, 'test-supervisor')['released']
    with solar_state.session() as store:
        assert store.task_claim_detail(parent, 'synthesis')['claimed']
    mirror(root)
    marker = tmp_path / 'synthesis-called'
    capture_router_prompt(monkeypatch)
    result = run_executor(path, root, '<delivery>Final synthesis</delivery>', tmp_path, marker=marker)
    assert result.returncode == 0, result.stderr
    assert marker.exists()
    instructions, context = marker.read_text().split('Generated execution context (non-authoritative):', 1)
    assert 'Known child failure' not in instructions and 'Known child failure' in context
    assert 'Review text' in context
    with solar_state.session() as store:
        body = store.task_get(parent)['body']
        assert 'Known child failure' in body and 'error' in body and 'Final synthesis' in body
        assert len(list(store.conn.execute("SELECT 1 FROM audit WHERE event='subtask_synthesis_started'"))) == 1
    marker.unlink()
    with solar_state.session() as store:
        monkeypatch.setenv("SOLAR_TASK_TOKEN", store.reservation_for(parent)["token"])
    result = run_executor(path, root, 'must not synthesize twice', tmp_path, marker=marker)
    assert result.returncode == 1
    assert not marker.exists()


@pytest.mark.parametrize('change', ['source', 'missing', 'manifest', 'profile', 'removed-profile'])
def test_child_source_or_snapshot_change_returns_to_preparation(tmp_path, change):
    root = make_root(tmp_path)
    source, parent, path, declarations = approved(root, tmp_path)
    assert run_executor(path, root, block(declarations), tmp_path).returncode == 20
    with solar_state.session() as store:
        ids = [entry.split('=')[1] for entry in store.task_field(parent, 'subtask_ids').split(',')]
        store.task_await(parent, ids, token=store.reservation_for(parent)['token'])
        assert store.task_adopt(parent, 'test-supervisor')['released']
        assert store.task_claim_detail(ids[0], 'child')['claimed']
        if change == 'source':
            source.write_text('Changed evidence')
        elif change == 'missing':
            source.unlink()
        elif change == 'manifest':
            store.task_set(ids[0], 'review_input_manifest', json.dumps('{}'))
        elif change == 'profile':
            store.task_set(ids[0], 'execution_profile', json.dumps('changed-profile'))
        else:
            store.task_unset(ids[0], 'execution_profile')
    mirror(root)
    marker = tmp_path / 'provider-must-not-start'
    result = run_executor(root / 'active' / f'{ids[0]}.md', root, 'not called', tmp_path, marker=marker)
    assert result.returncode == 1
    assert not marker.exists()
    with solar_state.session() as store:
        assert store.task_status(ids[0]) == 'draft'
        assert store.reservation_for(ids[0])["phase"] == "ending"
        assert store.task_adopt(ids[0], "test-supervisor")["released"]
        assert store.reservation_for(ids[0]) is None


def test_no_policy_never_creates_children(tmp_path):
    root = make_root(tmp_path)
    path = write_parent(root)
    result = run_executor(path, root, block([dict(title='Review',body='Review A',provider='claude')]), tmp_path)
    assert result.returncode == 1
    with solar_state.session() as store:
        assert len(store.task_list()) == 1
        assert 'subtask_authorization_required' in store.task_get('parent-0001-aaaa')['body']
        assert not list(store.conn.execute('SELECT * FROM task_authorizations'))


def test_interrupted_legacy_manifest_does_not_backfill_authority(tmp_path):
    root = make_root(tmp_path)
    path = write_parent(root, extra='subtask_ids: "legacy=,other="\n')
    (root / 'subtasks').mkdir()
    (root / 'subtasks/parent-0001-aaaa.json').write_text(json.dumps([dict(title='A',body='x'),dict(title='B',body='x')]))
    marker = tmp_path / 'provider-called'
    result = run_executor(path, root, 'not called', tmp_path, marker=marker)
    assert result.returncode == 1
    assert not marker.exists()
    with solar_state.session() as store:
        assert len(store.task_list()) == 1


def test_a_busy_state_at_start_never_withdraws_an_approval(tmp_path):
    """A lock that is not granted in time (a cutover, an update) says nothing about the approval."""
    import os, subprocess, sys
    from test_subtask_worker import EXECUTE, ROUTER_STUB, SCRIPTS
    from queue_mirror import env_for, task_id_of
    root = make_root(tmp_path)
    source, parent, path, declarations = approved(root, tmp_path)
    skills = SCRIPTS.parents[1]
    wrapper = tmp_path / 'busy_snapshot.py'
    wrapper.write_text(f'''import runpy, sys
sys.path[:0] = {[str(SCRIPTS), str(skills / 'solar-state/scripts'), str(skills / 'solar-paths/scripts')]!r}
import solar_state
def busy(self, *args, **kwargs):
    raise solar_state.StateBusy('state lock not granted in time (a cutover is running)')
solar_state.Session.execution_snapshot = busy
sys.argv = [{str(EXECUTE)!r}] + sys.argv[1:]
runpy.run_path({str(EXECUTE)!r}, run_name='__main__')
''')
    router = tmp_path / 'router_stub.py'
    router.write_text(ROUTER_STUB, encoding='utf-8')
    seed(root)
    proc = subprocess.run([sys.executable, str(wrapper), task_id_of(path), str(router)], capture_output=True,
                          text=True, env=env_for(root, dict(os.environ)), timeout=120)
    assert proc.returncode != 0
    with solar_state.session() as store:
        task = store.task_get(parent)
        assert store.task_status(parent) == 'active', 'the task was sent back to draft by a transient error'
        assert solar_state.approval_state(task['frontmatter'], task['body']) is None
        assert 'review_preparation_required' not in [r[0] for r in store.conn.execute('SELECT event FROM audit')]


def _question(root, notify_when, tmp_path):
    """An approved, claimed question (ask_readonly_v1) the executor can run with the router double."""
    import execution_profiles as ep
    workspace = tmp_path / 'workspace'
    workspace.mkdir(exist_ok=True)
    built = ep.build_ask_envelope(provider='codex', prompt='Return the brief', cwd=str(workspace), model=None)
    seed(root)
    with solar_state.session() as store:
        fields = [('title', json.dumps('Brief')), ('provider', json.dumps('codex')),
                  ('access_policy', json.dumps(dict(version=1, mode='read', scopes=[str(workspace)], resources=[]))),
                  ('execution_profile', json.dumps('ask_readonly_v1')),
                  ('review_input_manifest', json.dumps(built['manifest'])),
                  ('review_input_digest', json.dumps(built['review_input_digest']))]
        if notify_when:
            fields.append(('notify_when', notify_when))
        task = store.task_create(fields, '\n# Brief\n\nReturn the brief.\n')
        store.task_approve(task, expected_row_version=store.task_get(task)['row_version'])
        assert store.task_claim_detail(task, 'test')['claimed']
    mirror(root)
    return task


def _body_of(task):
    with solar_state.session() as store:
        return store.task_get(task)['body']


def test_a_question_that_asks_for_delivery_records_the_block_of_the_run(tmp_path):
    root = make_root(tmp_path)
    task = _question(root, 'delivery,failed', tmp_path)
    result = run_executor(root / 'active' / f'{task}.md', root, 'Work.\n<delivery>\nDECISION: nueva\n</delivery>', tmp_path)
    assert result.returncode == 0, result.stderr
    assert '## Delivery\n\nDECISION: nueva' in _body_of(task)
    with solar_state.session() as store:
        assert store.task_field(task, 'delivery_recorded') == 'true'


def test_a_question_without_a_block_records_nothing(tmp_path):
    root = make_root(tmp_path)
    task = _question(root, 'delivery,failed', tmp_path)
    result = run_executor(root / 'active' / f'{task}.md', root, 'Nothing new today.', tmp_path)
    assert result.returncode == 0, result.stderr
    assert '## Delivery' not in _body_of(task)
    with solar_state.session() as store:
        assert not store.task_field(task, 'delivery_recorded')


@pytest.mark.parametrize('notify_when', ['completed', 'completed,failed', ''])
def test_a_question_that_did_not_ask_for_delivery_keeps_its_old_behaviour(tmp_path, notify_when):
    root = make_root(tmp_path)
    task = _question(root, notify_when, tmp_path)
    result = run_executor(root / 'active' / f'{task}.md', root, '<delivery>ignored</delivery>', tmp_path)
    assert result.returncode == 0, result.stderr
    assert '## Delivery' not in _body_of(task)
