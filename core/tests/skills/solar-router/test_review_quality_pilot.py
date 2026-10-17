"""Offline pilot preparation/report checks; no account or provider calls."""
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / 'support/review_quality_pilot.py'
_SPEC = importlib.util.spec_from_file_location('review_quality_pilot', _PATH)
pilot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pilot)


def prepared(tmp_path):
    destination = tmp_path / 'pilot'
    pilot.prepare(destination, 'simulated-model-for-offline-validation')
    return destination


def synthetic_results(destination):
    data = json.loads((destination / 'results.json').read_text())
    data['authorization'] = dict(operator='offline-test-double', account_reference='fake-account',
                                 approval_reference='fake-approval', authorized_at='2026-10-17T10:00:00+00:00',
                                 max_cost_usd=1)
    for run in data['runs']:
        rejected = run['case'] == 'changed-source' and run['arm'] == 'package'
        output = f"{run['case']}-{run['arm']}.txt"
        (destination / output).write_text('Synthetic test result; not a real pilot.')
        run.update(status='rejected_before_launch' if rejected else 'completed',
                   output_file=output, started_at='2026-10-17T10:00:00+00:00',
                   finished_at='2026-10-17T10:00:01+00:00', elapsed_seconds=1,
                   input_tokens=0, output_tokens=0, cost_usd=0,
                   source_freshness='review_input_mismatch' if rejected else 'current',
                   omissions=0, false_positives=0, detection_score=2,
                   evidence_score=2, freshness_score=2)
    return data


def test_preparation_captures_then_changes_source_without_inference(tmp_path):
    destination = prepared(tmp_path)
    manifest = json.loads((destination / 'pilot.json').read_text())
    assert manifest['status'] == 'prepared_not_executed'
    assert [case['offline_preflight'] for case in manifest['cases']] == [
        'current', 'current', 'review_input_mismatch']
    assert len(json.loads((destination / 'results.json').read_text())['runs']) == 6
    with pytest.raises(FileExistsError):
        pilot.prepare(destination, 'another-model')
    with pytest.raises(ValueError, match='Record operator'):
        pilot.report(destination)


def test_aggregate_synthetic_pairs_cannot_authorize_rollout(tmp_path):
    destination = prepared(tmp_path)
    pilot.write_json(destination / 'results.json', synthetic_results(destination))
    result = pilot.report(destination)
    assert result['quality_gate_passed'] is True
    assert result['within_budget'] is True
    assert result['rollout_authorized'] is False


@pytest.mark.parametrize('mutation,error', [
    (lambda data: data['runs'].pop(), 'exactly one'),
    (lambda data: data['runs'][0].update(model='different'), 'same exact model'),
    (lambda data: data['runs'][-1].update(status='completed'), 'not refused before launch'),
    (lambda data: data['runs'][0].update(source_freshness='changed'), 'Source freshness'),
    (lambda data: data['runs'][-1].update(cost_usd=0.1), 'zero inference'),
    (lambda data: data['runs'][0].update(cost_usd=None), 'measurement required'),
])
def test_invalid_or_incomplete_results_are_refused(tmp_path, mutation, error):
    destination = prepared(tmp_path)
    data = synthetic_results(destination)
    mutation(data)
    pilot.write_json(destination / 'results.json', data)
    with pytest.raises(ValueError, match=error):
        pilot.report(destination)
