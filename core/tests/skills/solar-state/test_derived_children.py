"""Derived children cross the same approval/admission gate as all other tasks."""
import json
import pytest
import solar_state
from review_inputs import create_parent, batch


@pytest.fixture
def store(ready):
    with solar_state.session(ready, auto_backup=False) as store:
        yield store


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'evidence.txt'
    path.write_text('Approved evidence.\n')
    return path


def test_three_children_are_atomic_idempotent_and_synthesize_once(store, source):
    parent, token, declarations, catalog = create_parent(store, source)
    children = store.materialize_children(parent, declarations, token=token)
    assert len(children) == 3
    assert store.materialize_children(parent, declarations, token=token) == children
    assert len(store.task_list()) == 4
    assert store.conn.execute('SELECT COUNT(*) FROM task_links').fetchone()[0] == 3
    provenance = list(store.conn.execute('SELECT * FROM task_authorizations'))
    assert len(provenance) == 3
    for row in provenance:
        assert row['parent_digest'] == store.task_field(parent, 'approved_digest')
        assert row['manifest_digest'] == store.task_field(parent, 'review_input_digest')
        child = store.task_get(row['task_id'])
        assert solar_state.approval_state(child['frontmatter'], child['body']) is None
        assert store.task_field(row['task_id'], 'approved_digest') != row['parent_digest']
    assert store.synthesis_begin(parent, token=token) is False
    store.task_await(parent, [child['id'] for child in children], token=token)
    for i, child in enumerate(children):
        claimed = store.task_claim_detail(child['id'], 'test-child')
        assert claimed['claimed']
        if i == 1:
            store.task_fail(child['id'], 'Review failed', token=claimed['token'])
        else:
            store.task_complete(child['id'], token=claimed['token'])
    claimed = store.task_claim_detail(parent, 'synthesizer')
    assert claimed['claimed']
    assert store.synthesis_begin(parent, token=claimed['token'])
    assert not store.synthesis_begin(parent, token=claimed['token'])
    event = store.conn.execute("SELECT row FROM audit WHERE event='subtask_synthesis_started'").fetchone()
    assert any(child['status'] == 'error' for child in json.loads(event[0])['children'])
    assert store.async_policy()['global_capacity'] == 1
    assert store.async_policy()['enabled_reader_profiles'] == []


@pytest.mark.parametrize('change', ['no-policy', 'no-digest', 'bad-digest', 'template', 'provider', 'volume', 'subset', 'cancel', 'revoke', 'wrong-token'])
def test_bad_declarations_or_parent_create_nothing(store, source, change):
    parent, token, declarations, _ = create_parent(store, source)
    if change == 'no-policy':
        store.task_unset(parent, 'subtask_policy')
    elif change == 'no-digest':
        store.task_unset(parent, 'review_input_digest')
    elif change == 'bad-digest':
        store.task_set(parent, 'review_input_digest', json.dumps('0' * 64))
    elif change == 'template':
        declarations[1]['body'] = 'Do unapproved work'
    elif change == 'provider':
        declarations[0]['provider'] = 'codex'
    elif change == 'volume':
        declarations += declarations
    elif change == 'subset':
        declarations = declarations[:1]
    elif change == 'cancel':
        store.cancellation_request(parent)
    elif change == 'revoke':
        store.task_set_body(parent, 'Changed approved instructions')
    elif change == 'wrong-token':
        token = 'not-the-current-token'
    with pytest.raises(solar_state.StateError):
        store.materialize_children(parent, declarations, token=token)
    assert len(store.task_list()) == 1
    assert not list(store.conn.execute('SELECT * FROM task_authorizations'))
    assert not list(store.conn.execute('SELECT * FROM task_links'))


def test_child_edit_and_parent_edit_invalidate_claims(store, source):
    parent, token, declarations, _ = create_parent(store, source)
    children = store.materialize_children(parent, declarations, token=token)
    store.task_release(parent, 'test-parent', token=token)
    store.task_set_body(children[0]['id'], 'Modified child')
    assert store.task_claim_detail(children[0]['id'], 'w')['reason'] == 'mismatch'
    with pytest.raises(solar_state.StateError):
        claimed = store.task_claim_detail(parent, 'test-parent')
        store.materialize_children(parent, declarations, token=claimed['token'])
    store.task_release(parent, 'test-parent', token=claimed['token'])
    store.task_set_body(parent, 'Modified parent')
    assert store.task_claim_detail(children[1]['id'], 'w')['reason'] == 'parent_revoked'


def test_legacy_children_are_not_authorized_by_parent_link(store, source):
    parent, token, _, _ = create_parent(store, source)
    child = store.task_create([('parent_task_id', json.dumps(parent))], 'Legacy', status='queued')
    store.task_release(parent, 'test-parent', token=token)
    assert store.task_claim_detail(child, 'w')['reason'] == 'subtask_authorization_required'
    assert store.legacy_children()[0]['executable'] is False


def test_five_is_a_hard_limit(store, source):
    fields, declarations, _ = batch(source, 5)
    parent = store.task_create(fields, 'Synthesize', status='queued')
    claimed = store.task_claim_detail(parent, 'w')
    assert len(store.materialize_children(parent, declarations, token=claimed['token'])) == 5


def test_concurrent_retries_materialize_one_batch(ready, source):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with solar_state.session(ready, auto_backup=False) as store:
        parent, token, declarations, _ = create_parent(store, source)
    barrier = Barrier(3)
    def attempt():
        with solar_state.session(ready, auto_backup=False) as store:
            barrier.wait(timeout=10)
            return store.materialize_children(parent, declarations, token=token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        barrier.wait(timeout=10)
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    with solar_state.session(ready, auto_backup=False) as store:
        assert len(store.task_list()) == 4
        assert store.conn.execute('SELECT COUNT(*) FROM task_authorizations').fetchone()[0] == 3
        assert store.conn.execute('SELECT COUNT(*) FROM task_links').fetchone()[0] == 3


def test_forged_manifest_provenance_is_not_executable(store, source):
    parent, token, declarations, _ = create_parent(store, source)
    children = store.materialize_children(parent, declarations, token=token)
    store.task_release(parent, 'test-parent', token=token)
    store.conn.execute('UPDATE task_authorizations SET manifest_digest = ?', ('0' * 64,))
    assert store.task_claim_detail(children[0]['id'], 'w')['reason'] == 'subtask_authorization_required'


@pytest.mark.parametrize('change', ['parent-cancel', 'parent-edit', 'child-edit'])
def test_running_child_uses_existing_cancellation_protocol_when_authority_is_lost(store, source, change):
    parent, token, declarations, _ = create_parent(store, source)
    children = store.materialize_children(parent, declarations, token=token)
    store.task_await(parent, [c['id'] for c in children], token=token)
    child = children[0]['id']
    claimed = store.task_claim_detail(child, 'reader')
    assert claimed['claimed'] and not store.cancellation_requested(child)
    if change == 'parent-cancel':
        store.cancellation_request(parent)
    elif change == 'parent-edit':
        store.task_set_body(parent, 'Unapproved parent')
    else:
        store.task_set_body(child, 'Unapproved child')
    assert store.cancellation_requested(child)
    assert child in store.cancellation_ids()
    # Reservation stays until the executor/supervisor has verified cleanup.
    assert store.reservation_for(child)['token'] == claimed['token']
    store.task_complete(child, cancelled=True, token=claimed['token'])
    assert store.task_status(child) == 'cancelled'


def test_registry_keeps_packet_claude_only_and_adds_repository_and_ask_readers_without_enabling_them(store):
    assert solar_state.VERIFIED_PROFILES == {'text_only_review_v1': frozenset({'claude'}),
        'repository_readonly_v1': frozenset({'claude', 'codex', 'agent', 'agy'}),
        'ask_readonly_v1': frozenset({'claude', 'codex', 'agent', 'agy'})}
    assert store.async_policy()['enabled_reader_profiles'] == []


def test_reprepare_requires_an_actual_current_reservation(store):
    task = store.task_import('---\nid: legacy-active\nstatus: active\n---\nLegacy active task')
    with pytest.raises(solar_state.StaleToken):
        store.task_reprepare(task, 'unrelated-token', 'review_input_mismatch')
    assert store.task_status(task) == 'active'


def test_reprepare_withdraws_approval_and_releases_exact_token(store, source):
    parent, token, declarations, _ = create_parent(store, source)
    child = store.materialize_children(parent, declarations, token=token)[0]['id']
    store.task_release(parent, 'test-parent', token=token)
    claimed = store.task_claim_detail(child, 'reader')
    assert claimed['claimed']
    store.task_reprepare(child, claimed['token'], 'review_input_mismatch')
    assert store.task_status(child) == 'draft'
    assert store.task_field(child, 'approved_digest') is None
    assert store.reservation_for(child) is None
    assert store.conn.execute("SELECT 1 FROM audit WHERE event='task_approval_withdrawn' AND json_extract(row,'$.task_id')=?", (child,)).fetchone()
