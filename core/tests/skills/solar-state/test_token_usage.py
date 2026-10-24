"""Durable native counters: approvals unchanged, partial failures, replay and reactivation."""
import json
import sqlite3

import pytest
import solar_state as st
import runtime_views
from reservation_tokens import token_of
from test_ask_concurrency import question


def active(store, provider='codex'):
    task = question(store, 'Meter', provider)
    assert store.task_claim_detail(task, 'worker')['claimed']
    token = token_of(store, task)
    return task, token


def observation(**usage):
    return dict(event_type='turn.completed', terminal=True, successful=True, usage=usage,
                model='model-a', session_id='synthetic-session')


def test_commit_reopen_replay_and_snapshot_unchanged(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        before = store.execution_snapshot(task, token)
        attempt = store.token_attempt_start(task, token, 'router-a', 'codex')
        store.token_attempt_launch(attempt, token, binary='/synthetic/codex', cli_version='1')
        item = observation(input_tokens=0, output_tokens=13, cached_input_tokens=8, future_counter=9)
        store.token_observe(attempt, token, 1, item)
        store.token_observe(attempt, token, 1, item)
        assert store.execution_snapshot(task, token) == before
        store.token_attempt_finish(attempt, token, 'success')
    with st.read_session(ready) as store:
        data = store.task_token_usage(task)
        assert len(data['attempts'][0]['observations']) == 1
        counts = data['attempts'][0]['metrics']
        assert counts['input_tokens'] == 0 and counts['output_tokens'] == 13
        assert counts['cache_write_tokens'] is None
        assert data['coverage']['cache_write_tokens'] == dict(available=0, launched=1)
        assert data['subtotals'][0]['metrics']['output_tokens']['subtotal'] == 13
        assert runtime_views.console_task_detail(store, task)['token_usage'] == data


def test_partial_crash_survives_without_terminal_and_never_becomes_zero(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        attempt = store.token_attempt_start(task, token, 'r', 'codex')
        store.token_attempt_launch(attempt, token, binary='codex', cli_version='1')
        store.token_observe(attempt, token, 1, dict(usage={'input_tokens': 8}, terminal=False))
    with st.read_session(ready) as store:
        d = store.task_token_usage(task)
        assert d['attempts'][0]['coverage'] == 'partial'
        assert d['attempts'][0]['reason'] == 'terminal_missing'
        assert d['attempts'][0]['metrics']['output_tokens'] is None
        assert not d['subtotals']


def test_error_zero_is_preserved_but_not_a_validated_success(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store, 'agy')
        attempt = store.token_attempt_start(task, token, 'r', 'agy')
        store.token_attempt_launch(attempt, token, binary='agy', cli_version='1')
        store.token_observe(attempt, token, 1, dict(terminal=True, successful=False,
                           usage={'input_tokens': 0, 'output_tokens': 0}))
        store.token_attempt_finish(attempt, token, 'failed')
        data = store.task_token_usage(task)
        assert data['attempts'][0]['observations'][0]['original']['usage']['input_tokens'] == 0
        assert data['attempts'][0]['metrics']['input_tokens'] is None
        assert not data['subtotals']


def test_privacy_conflicting_replay_and_stale_owner(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        attempt = store.token_attempt_start(task, token, 'r', 'codex')
        store.token_observe(attempt, token, 1, dict(usage={'input_tokens': 2, 'secret': 'hidden'},
                            result='private response', tools=['private']))
        original = store.task_token_usage(task)['attempts'][0]['observations'][0]['original']
        assert 'private' not in json.dumps(original) and 'hidden' not in json.dumps(original)
        with pytest.raises(st.FormatError, match='conflict'):
            store.token_observe(attempt, token, 1, observation(input_tokens=5))
        with pytest.raises(st.StaleToken):
            store.token_observe(attempt, 'old-token', 2, observation(input_tokens=5))
        store.task_release(task, 'worker', token=token)
        assert store.task_claim_detail(task, 'worker')['claimed']
        second = store.token_attempt_start(task, token_of(store, task), 'r2', 'codex')
        data = store.task_token_usage(task)['attempts']
        assert data[0]['execution_id'] != data[1]['execution_id']
        assert second != attempt


def test_rejected_launch_not_in_coverage_and_schema_unknown(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        attempt = store.token_attempt_start(task, token, 'r', 'codex')
        store.token_attempt_finish(attempt, token, 'not_launched')
        assert store.task_token_usage(task)['coverage']['input_tokens']['launched'] == 0


def test_v7_upgrade_is_new_backed_up_migration(ready):
    with st.session(ready, auto_backup=False) as store:
        store.conn.execute('DROP TABLE token_observations')
        store.conn.execute('DROP TABLE token_attempts')
        store.conn.execute('ALTER TABLE execution_reservations DROP COLUMN execution_id')
        store.conn.execute('PRAGMA user_version = 7')
    with st.cutover(ready) as cut:
        result = cut.upgrade_schema()
    assert result['from_version'] == 7 and result['to_version'] == st.SCHEMA_VERSION
    assert result['backup']
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        assert store.reservation_for(task)['execution_id'] != token


def test_adoption_preserves_execution_but_rotates_private_owner(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        attempt = store.token_attempt_start(task, token, 'r', 'codex')
        execution = store.task_token_usage(task)['attempts'][0]['execution_id']
        store.token_attempt_launch(attempt, token, binary='fixture', cli_version='1')
        store.token_observe(attempt, token, 1, dict(usage={'input_tokens':1}, terminal=False))
        store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
        taken = store.task_adopt(task, 'replacement', identity=lambda pid: None, groups=lambda pgid: [])
        assert taken['adopted'] and taken['token'] != token
        assert store.reservation_for(task)['execution_id'] == execution
        with pytest.raises(st.StaleToken):
            store.token_observe(attempt, token, 1, observation(input_tokens=1))
        with pytest.raises(st.StateError, match='token_attempt_finished'):
            store.token_observe(attempt, taken['token'], 2, observation(input_tokens=1))
        abandoned = store.task_token_usage(task)['attempts'][0]
        assert abandoned['capture_error'] == 'owner_lost'
        assert abandoned['status'] == 'failed' and abandoned['coverage'] == 'partial'
        assert abandoned['observations'][0]['original']['usage']['input_tokens'] == 1
        retry = store.token_attempt_start(task, taken['token'], 'retry', 'codex')
        store.token_attempt_launch(retry, taken['token'], binary='fixture', cli_version='1')
        store.token_observe(retry, taken['token'], 1, observation(input_tokens=2))
        store.token_attempt_finish(retry, taken['token'], 'success')
        data = store.task_token_usage(task)
        assert len(data['attempts']) == 2
        assert {a['execution_id'] for a in data['attempts']} == {execution}
        assert data['subtotals'][0]['metrics']['input_tokens']['subtotal'] == 2


@pytest.mark.parametrize('second_success', [True, False])
def test_every_terminal_counts_towards_ambiguity_even_without_usage(ready, second_success):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        attempt = store.token_attempt_start(task, token, 'r', 'codex')
        store.token_attempt_launch(attempt, token, binary='codex', cli_version='1')
        store.token_observe(attempt, token, 1, observation(input_tokens=10))
        store.token_observe(attempt, token, 2, dict(terminal=True, successful=second_success))
        store.token_attempt_finish(attempt, token, 'success')
        data = store.task_token_usage(task)
        assert data['attempts'][0]['reason'] == 'ambiguous_terminals'
        assert data['attempts'][0]['coverage'] == 'partial'
        assert data['attempts'][0]['metrics']['input_tokens'] is None
        assert not data['subtotals']


def test_multimodel_aggregate_never_belongs_to_last_intermediate_model(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store, 'claude')
        attempt = store.token_attempt_start(task, token, 'r', 'claude')
        store.token_attempt_launch(attempt, token, binary='/private/path/client', cli_version='1')
        store.token_observe(attempt, token, 1, dict(model='model-a', usage={'input_tokens':1}))
        store.token_observe(attempt, token, 2, dict(terminal=True,successful=True,model='model-a',
            usage={'input_tokens':20},model_usage={'model-a':{'inputTokens':10},'model-b':{'inputTokens':10}}))
        store.token_attempt_finish(attempt, token, 'success')
        data = store.task_token_usage(task)
        assert data['attempts'][0]['model'] is None
        assert data['subtotals'][0]['model'] is None
        assert data['subtotals'][0]['metrics']['input_tokens']['subtotal'] == 20
        assert '/private/path/client' not in json.dumps(data)


def test_same_activation_cannot_launch_two_live_attempts(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        attempt = store.token_attempt_start(task, token, 'first', 'codex')
        with pytest.raises(st.StateError, match='token_attempt_already_active'):
            store.token_attempt_start(task, token, 'duplicate', 'codex')
        store.token_attempt_finish(attempt, token, 'not_launched')
        other = store.token_attempt_start(task, token, 'retry', 'codex')
        assert other != attempt


def test_v7_existing_reservations_receive_public_identity_and_accept_measurement(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        store.conn.execute('DROP TABLE token_observations')
        store.conn.execute('DROP TABLE token_attempts')
        store.conn.execute('ALTER TABLE execution_reservations DROP COLUMN execution_id')
        store.conn.execute('PRAGMA user_version = 7')
    with st.cutover(ready) as cut:
        cut.upgrade_schema()
    with st.session(ready, auto_backup=False) as store:
        reservations = store.reservations()
        assert all(r['execution_id'] and r['execution_id'] != r['token'] for r in reservations)
        attempt = store.token_attempt_start(task, token, 'after-upgrade', 'codex')
        assert store.task_token_usage(task)['attempts'][0]['id'] == attempt


@pytest.mark.parametrize('odd_model', ['claude-opus[1m]', 'model@version', 'invalid model'])
def test_model_key_selection_never_turns_multimodel_usage_into_single_model(ready, odd_model):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store, 'claude')
        attempt = store.token_attempt_start(task, token, 'r', 'claude')
        store.token_attempt_launch(attempt, token, binary='fixture', cli_version='1')
        store.token_observe(attempt, token, 1, dict(terminal=True,successful=True,usage={'input_tokens':20},
            model_usage={odd_model:{'input_tokens':10},'model-b':{'input_tokens':10}}))
        store.token_attempt_finish(attempt, token, 'success')
        data = store.task_token_usage(task)
        a = data['attempts'][0]
        assert a['model'] is None and data['subtotals'][0]['model'] is None
        original = a['observations'][0]['original']
        if ' ' in odd_model:
            assert original['model_usage_keys_dropped'] == 1
        else:
            assert odd_model in original['model_usage']


def test_partial_attempt_keeps_native_counters_only_in_evidence(ready):
    with st.session(ready, auto_backup=False) as store:
        task, token = active(store)
        a = store.token_attempt_start(task, token, 'r', 'codex')
        store.token_attempt_launch(a, token, binary='fixture', cli_version='1')
        store.token_observe(a, token, 1, observation(input_tokens=10))
        store.token_attempt_finish(a, token, 'failed')
        data = store.task_token_usage(task)
        assert data['attempts'][0]['coverage'] == 'partial'
        assert all(v is None for v in data['attempts'][0]['metrics'].values())
        assert data['attempts'][0]['observations'][0]['original']['usage']['input_tokens'] == 10
        assert not data['subtotals']
