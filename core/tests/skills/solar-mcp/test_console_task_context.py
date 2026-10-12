"""Shared parsing preserves MCP refusals and localizes console errors."""
import json
import solar_state
import runtime_views


def test_console_context_reads_without_mutating(solar_env):
    checkpoint = {'next_check': {'at': '2026-10-13', 'action': 'Review'}, 'wait': 'Owner review'}
    with solar_state.session() as store:
        task_id = store.task_create([('agent', 'fixture'), ('continuity_checkpoint', json.dumps(checkpoint))])
        before = store.task_export(task_id)
    with solar_state.read_session() as store:
        result = runtime_views.console_task_detail(store, task_id)
        assert result['context']['continuity_checkpoint'] == checkpoint
        assert store.task_export(task_id) == before
        assert runtime_views.console_task_detail(store, 'missing') is None


def test_invalid_context_is_local_to_detail(solar_env):
    with solar_state.session() as store:
        task_id = store.task_create([('continuity_checkpoint', '[]'), ('scheduled_timezone', 'Europe/Madrid')])
    with solar_state.read_session() as store:
        result = runtime_views.console_task_detail(store, task_id)
        assert result['context_error'] == 'continuity_checkpoint must be a JSON object'
        assert result['configuration']['scheduled_timezone'] == 'Europe/Madrid'
        assert runtime_views.console_tasks(store)['tasks'][0]['id'] == task_id


def test_mcp_and_console_share_checkpoint_semantics(solar_env):
    import task_views
    import pytest
    from mcp_context import OperationError
    assert task_views._checkpoint({}) is None
    checkpoint = {'wait': 'Review', 'note': 'quotes " and accents á'}
    raw = json.dumps(checkpoint)
    assert task_views._checkpoint({'continuity_checkpoint': raw}) == runtime_views.task_checkpoint(raw)
    for raw in ('[]', 'null', 'broken', None):
        with pytest.raises(OperationError) as refusal:
            task_views._checkpoint({'continuity_checkpoint': raw})
        assert refusal.value.code == 'checkpoint_invalid'
        with pytest.raises(ValueError):
            runtime_views.task_checkpoint(raw)
