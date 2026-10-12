"""One checkpoint parser: MCP keeps its refusal, the console reports a stable code."""
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
        assert result['context_error'] == 'checkpoint_invalid'
        assert result['context'] is None
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
        assert refusal.value.args[0] == 'continuity_checkpoint must be a JSON object'
        with pytest.raises(ValueError):
            runtime_views.task_checkpoint(raw)


def test_console_and_mcp_return_the_same_decoded_checkpoint(solar_env):
    import task_views
    checkpoint = {'wait': 'Review', 'next_check': {'at': '2026-10-13'}}
    with solar_state.session() as store:
        task_id = store.task_create([('continuity_checkpoint', json.dumps(checkpoint))])
    with solar_state.read_session() as store:
        console = runtime_views.console_task_detail(store, task_id)['context']['continuity_checkpoint']
    assert console == task_views._checkpoint({'continuity_checkpoint': json.dumps(checkpoint)}) == checkpoint
