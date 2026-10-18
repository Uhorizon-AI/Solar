"""Approved child materialization through the real executor, with a router double."""
import json
from pathlib import Path
import pytest
import solar_state
from review_inputs import create_parent
from queue_mirror import seed, mirror
from test_subtask_worker import make_root, run_executor, block, write_parent


def approved(root, tmp_path):
    source = tmp_path / 'evidence.txt'
    source.write_text('Evidence to review.\n')
    seed(root)
    with solar_state.session() as store:
        parent, token, declarations, catalog = create_parent(store, source)
    mirror(root)
    return source, parent, root / 'active' / f'{parent}.md', declarations


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
    result = run_executor(path, root, '<delivery>Final synthesis</delivery>', tmp_path, marker=marker)
    assert result.returncode == 0, result.stderr
    assert marker.exists()
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
