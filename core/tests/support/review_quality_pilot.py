#!/usr/bin/env python3
"""Prepare/validate a review-quality pilot offline. Never launches a provider."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills/solar-router/scripts'))
import execution_profiles as profiles

CASES = {
    'contradiction': {
        'sources': {'requirements.md': 'The supported maximum batch size is three.\n',
                    'operations.md': 'The supported maximum batch size is five.\n'},
        'expected': 'Identify conflicting batch limits and cite both documents; do not choose one without authority.',
    },
    'omitted-datum': {
        'sources': {'requirements.md': 'Release only after the latency target has been met.\n',
                    'measurements.md': 'Observed latency: 120 ms. The target was not supplied.\n'},
        'expected': 'Report insufficient information: the required latency target is missing; do not invent it.',
    },
    'changed-source': {
        'sources': {'requirements.md': 'The approved retry limit is two.\n'},
        'expected': 'Reject the stale package before provider launch with review_input_mismatch; no package inference cost.',
    },
}
INSTRUCTIONS = 'Identify contradictions, missing decision-critical data, and source freshness limitations. Cite source paths. Do not approve a release.'
RULES = ['Separate findings from uncertainty.', 'Do not invent missing requirements.',
         'A captured package is not a live repository verification.']


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def prepare(destination: Path, model: str):
    # Refuse reuse instead of overwriting evidence from a previous pilot.
    destination.mkdir(parents=True, exist_ok=False)
    cases = []
    for name, case in CASES.items():
        folder = destination / name
        folder.mkdir()
        evidence = []
        for filename, content in case['sources'].items():
            source = folder / filename
            source.write_text(content, encoding='utf-8')
            evidence.append(dict(path=str(source.resolve()), content=content,
                                 sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        envelope = profiles.build_review_envelope_v1(
            instructions=INSTRUCTIONS, rules=RULES, evidence=evidence, provider='claude', model=model)
        write_json(folder / 'envelope.json', envelope)
        if name == 'changed-source':
            (folder / 'requirements.md').write_text('The approved retry limit is four.\n', encoding='utf-8')
        try:
            profiles.verify_sources(envelope['manifest'], [str(folder.resolve())])
            freshness = 'current'
        except profiles.ProfileError as error:
            freshness = error.code
        if (freshness == 'review_input_mismatch') != (name == 'changed-source'):
            raise ValueError('Unexpected offline source-validation result')
        cases.append(dict(case=name, expected=case['expected'], capture_digest=envelope['review_input_digest'],
                          offline_preflight=freshness))
    manifest = dict(version=1, prepared_at=datetime.now(timezone.utc).isoformat(),
                    provider='claude', model=model, rubric='review-quality-v1',
                    status='prepared_not_executed', instructions=INSTRUCTIONS, rules=RULES, cases=cases)
    write_json(destination / 'pilot.json', manifest)
    runs = []
    for case in cases:
        for arm in ('live', 'package'):
            runs.append(dict(case=case['case'], arm=arm, model=model, rubric=manifest['rubric'],
                             status='not_run', output_file=None, started_at=None, finished_at=None,
                             elapsed_seconds=None, input_tokens=None, output_tokens=None, cost_usd=None,
                             capture_digest=case['capture_digest'],
                             source_freshness=None, omissions=None, false_positives=None,
                             detection_score=None, evidence_score=None, freshness_score=None,
                             notes='Record actual observations only; null means not measured.'))
    write_json(destination / 'results.json', dict(authorization=None, runs=runs))
    return manifest


def report(destination: Path):
    manifest = json.loads((destination / 'pilot.json').read_text())
    results = json.loads((destination / 'results.json').read_text())
    authorization = results.get('authorization')
    if not isinstance(authorization, dict) or not all(authorization.get(key) for key in
            ('operator', 'account_reference', 'approval_reference', 'authorized_at')):
        raise ValueError('Record operator, account_reference, approval_reference and authorized_at first; never store credentials')
    budget = authorization.get('max_cost_usd')
    if isinstance(budget, bool) or not isinstance(budget, (float, int)) or budget < 0:
        raise ValueError('Record a nonnegative authorized max_cost_usd')
    runs = results['runs']
    expected = {(case['case'], arm) for case in manifest['cases'] for arm in ('live', 'package')}
    if len(runs) != len(expected) or {(run['case'], run['arm']) for run in runs} != expected:
        raise ValueError('Need exactly one live/package pair for every prepared case')
    for run in runs:
        if run['model'] != manifest['model'] or run['rubric'] != manifest['rubric']:
            raise ValueError('Every arm must use the same exact model and rubric')
        case = next(case for case in manifest['cases'] if case['case'] == run['case'])
        if run['capture_digest'] != case['capture_digest']:
            raise ValueError('Result capture digest differs from the prepared case')
        rejected = run['case'] == 'changed-source' and run['arm'] == 'package'
        if run['status'] != ('rejected_before_launch' if rejected else 'completed'):
            raise ValueError('Pilot incomplete or changed-source package was not refused before launch')
        if run['source_freshness'] != ('review_input_mismatch' if rejected else 'current'):
            raise ValueError('Source freshness missing or changed after review; recapture and reapprove')
        for field in ('elapsed_seconds', 'input_tokens', 'output_tokens', 'cost_usd', 'omissions', 'false_positives'):
            value = run[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f'Missing/nonnegative measurement required: {field}')
        for field in ('detection_score', 'evidence_score', 'freshness_score'):
            if type(run[field]) is not int or run[field] not in (0, 1, 2):
                raise ValueError(f'Score must be 0, 1 or 2: {field}')
        if rejected and any(run[field] for field in ('input_tokens', 'output_tokens', 'cost_usd')):
            raise ValueError('A refused package must have zero inference usage/cost')
        for field in ('started_at', 'finished_at'):
            timestamp = datetime.fromisoformat(run[field])
            if timestamp.tzinfo is None:
                raise ValueError('Timestamps must include a timezone')
        if datetime.fromisoformat(run['finished_at']) < datetime.fromisoformat(run['started_at']):
            raise ValueError('Finish precedes start')
        output = (destination / run['output_file']).resolve()
        if destination.resolve() not in output.parents or not output.is_file():
            raise ValueError('Each result needs an evidence output file inside the pilot directory')
    cost = sum(run['cost_usd'] for run in runs)
    passed = all(run['detection_score'] == 2 and run['freshness_score'] == 2
                 and run['evidence_score'] == 2 and run['omissions'] == 0
                 and run['false_positives'] == 0 for run in runs)
    return dict(status='recorded_results_require_operator_review', model=manifest['model'],
                rubric=manifest['rubric'], total_cost_usd=cost, within_budget=cost <= budget,
                quality_gate_passed=passed, rollout_authorized=False, runs=runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'report'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--model', help='Exact approved model ID; required for preparation')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            if not args.model:
                parser.error('--model is required for prepare')
            result = prepare(args.directory.resolve(), args.model)
        else:
            result = report(args.directory.resolve())
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
