"""The gate audit holds a decision row and an outcome row per call; only decisions are decisions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[3] / 'skills/solar-app/scripts'
sys.path.insert(0, str(SCRIPTS))
import console_data


def decision(ts, tool, allowed, code='ok', trace='t'):
    return dict(ts=ts, kind='decision', tool=tool, allowed=allowed, code=code, trace_id=trace)


def outcome(ts, tool, trace='t'):
    return dict(ts=ts, kind='outcome', tool=tool, trace_id=trace, ok=True, code='ok', detail='')


class GateDecisions(unittest.TestCase):
    def read(self, lines):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'audit.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            with patch.object(console_data.solar_runtime, 'runtime_dir', return_value=Path(tmp)):
                return console_data._gate_decisions()

    def test_only_decisions_are_counted_and_shown(self):
        gate = self.read([
            json.dumps(decision('2026-10-12T10:00:00Z', 'solar_task_approve', True, trace='a')),
            json.dumps(outcome('2026-10-12T10:00:00Z', 'solar_task_approve', trace='a')),
            json.dumps(decision('2026-10-12T10:01:00Z', 'solar_task_cancel', False, 'approval_required', trace='b')),
            json.dumps(dict(ts='2026-09-01T00:00:00Z', tool='solar_search', allowed=True, code='read_allowed')),
            json.dumps(dict(ts='2026-09-01T00:00:01Z', tool='solar_search', allowed=False, code='level_not_granted')),
            '{broken json',
            json.dumps(dict(ts='2026-10-12T10:02:00Z', tool='solar_search', note='no kind and no allowed')),
            json.dumps(dict(ts='2026-10-12T10:03:00Z', kind='unknown', tool='x', allowed=True)),
            json.dumps(['not', 'a', 'row']),
            '',
        ])
        self.assertEqual((gate['total'], gate['allowed']), (4, 2))
        self.assertEqual([(row['tool'], row['allowed']) for row in gate['last']],
                         [('solar_task_approve', True), ('solar_task_cancel', False), ('solar_search', True), ('solar_search', False)])
        self.assertEqual(set(gate), {'total', 'allowed', 'last'})
        self.assertEqual(set(gate['last'][0]), {'ts', 'tool', 'allowed', 'code'})

    def test_an_outcome_never_looks_like_a_denial(self):
        gate = self.read([json.dumps(decision('2026-10-12T10:00:00Z', 't', True)), json.dumps(outcome('2026-10-12T10:00:00Z', 't'))])
        self.assertEqual((gate['total'], gate['allowed']), (1, 1))
        self.assertEqual([row['allowed'] for row in gate['last']], [True])
        # Same time, same call: one row, so no Allowed/Denied pair with the same timestamp.
        self.assertEqual(len({row['ts'] for row in gate['last']}), 1)

    def test_an_explicit_null_kind_counts_as_an_old_row(self):
        # `kind` present but null is the same as no `kind`: both are pre-kind rows,
        # and they count on their boolean `allowed`.
        gate = self.read([
            json.dumps(dict(ts='2026-09-01T00:00:00Z', kind=None, tool='solar_search', allowed=True, code='read_allowed')),
            json.dumps(dict(ts='2026-09-01T00:00:01Z', kind=None, tool='solar_search', allowed=False, code='level_not_granted')),
        ])
        self.assertEqual((gate['total'], gate['allowed']), (2, 1))
        self.assertEqual([row['allowed'] for row in gate['last']], [True, False])

    def test_a_non_boolean_allowed_is_not_a_decision(self):
        # A pre-kind row only counts when `allowed` is a real boolean; a string,
        # a number or a null is ignored instead of being drawn as a denial.
        gate = self.read([
            json.dumps(dict(ts='2026-09-01T00:00:00Z', tool='solar_search', allowed='true')),
            json.dumps(dict(ts='2026-09-01T00:00:01Z', tool='solar_search', allowed=1)),
            json.dumps(dict(ts='2026-09-01T00:00:02Z', tool='solar_search', allowed=None)),
            json.dumps(decision('2026-10-12T10:00:00Z', 'solar_task_approve', True, trace='a')),
        ])
        self.assertEqual((gate['total'], gate['allowed']), (1, 1))
        self.assertEqual([row['tool'] for row in gate['last']], ['solar_task_approve'])

    def test_only_the_last_twenty_decisions_are_listed(self):
        rows = []
        for i in range(30):
            rows.append(json.dumps(decision('2026-10-12T10:%02d:00Z' % i, 'tool%d' % i, True, trace=str(i))))
            rows.append(json.dumps(outcome('2026-10-12T10:%02d:00Z' % i, 'tool%d' % i, trace=str(i))))
        gate = self.read(rows)
        self.assertEqual(gate['total'], 30)
        self.assertEqual(len(gate['last']), 20)
        self.assertEqual(gate['last'][0]['tool'], 'tool10')
        self.assertEqual(gate['last'][-1]['tool'], 'tool29')

    def test_missing_or_empty_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(console_data.solar_runtime, 'runtime_dir', return_value=Path(tmp)):
                self.assertEqual(console_data._gate_decisions(), {'total': 0, 'allowed': 0, 'last': []})
        self.assertEqual(self.read([]), {'total': 0, 'allowed': 0, 'last': []})
