"""
Fail-closed tests for delegation_ctl.py (A3 mandates).

Every case runs against mandates and evidence created in a temporary directory
(`SOLAR_DELEGATIONS_DIR` / `SOLAR_DELEGATIONS_RUNTIME`). Live mandates under
`sun/delegations/` must never be touched: `activate` treats `shadow.jsonl` as
proof of real shadow execution, so a test writing there would forge the
prerequisite of the gate it is meant to verify.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import delegation_ctl

CTL = Path(delegation_ctl.__file__).resolve()

SHADOW_MANDATE = """
delegation:
  name: fixture-shadow
  owner: Fixture Owner
  mode: shadow
  objective: fixture mandate in shadow
  allowed_actions:
    - dry-run
    - validate
    - run
    - score
    - resolve
  systems:
    - fixture
  limits:
    frequency: every 4 hours
    volume: fixture
  stop_conditions:
    - mandate expired or revoked
  valid_from: "2026-01-01"
  expires_at: "2099-01-01"
  revoke_with: fixture
  evidence_log: fixture
""".lstrip()

ACTIVE_BAD_FREQ = """
delegation:
  name: fixture-bad-freq
  owner: Fixture Owner
  mode: active
  objective: fixture with unparseable frequency
  allowed_actions:
    - run
    - score
  systems:
    - fixture
  limits:
    frequency: on-demand or daily when scheduled
    max_items_per_day: 20
  stop_conditions:
    - repeated failures >= 3 consecutive runs
  valid_from: "2026-01-01"
  expires_at: "2099-01-01"
  revoke_with: fixture
  evidence_log: fixture
""".lstrip()

ACTIVE_MANDATE = """
delegation:
  name: fixture-active
  owner: Fixture Owner
  mode: active
  objective: fixture mandate with volume limits
  allowed_actions:
    - dry-run
    - run
    - score
  systems:
    - fixture
  limits:
    frequency: every 4 hours
    max_items_per_day: 20
  stop_conditions:
    - repeated failures >= 3 consecutive runs
  valid_from: "2026-01-01"
  expires_at: "2099-01-01"
  revoke_with: fixture
  evidence_log: fixture
""".lstrip()

EXPIRED_MANDATE = ACTIVE_MANDATE.replace("fixture-active", "fixture-expired").replace(
    'expires_at: "2099-01-01"', 'expires_at: "2026-01-02"'
)

INCOMPLETE_MANDATE = """
delegation:
  name: fixture-incomplete
  owner: Fixture Owner
  mode: active
  objective: missing limits/stop_conditions/expiry
  allowed_actions:
    - run
  systems:
    - fixture
  valid_from: "2026-01-01"
""".lstrip()


class DelegationCtlTestCase(unittest.TestCase):
    """Isolate mandate dir + evidence runtime for every test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.del_dir = tmp / "delegations"
        self.runtime = tmp / "runtime"
        self.del_dir.mkdir()
        self.runtime.mkdir()
        (self.del_dir / "fixture-shadow.yaml").write_text(SHADOW_MANDATE, encoding="utf-8")
        (self.del_dir / "fixture-active.yaml").write_text(ACTIVE_MANDATE, encoding="utf-8")
        (self.del_dir / "fixture-expired.yaml").write_text(EXPIRED_MANDATE, encoding="utf-8")
        (self.del_dir / "fixture-incomplete.yaml").write_text(INCOMPLETE_MANDATE, encoding="utf-8")
        (self.del_dir / "fixture-bad-freq.yaml").write_text(ACTIVE_BAD_FREQ, encoding="utf-8")
        self._orig = (delegation_ctl.DEL_DIR, delegation_ctl.RUNTIME)
        delegation_ctl.DEL_DIR = self.del_dir
        delegation_ctl.RUNTIME = self.runtime
        self.addCleanup(self._restore)

    def _restore(self):
        delegation_ctl.DEL_DIR, delegation_ctl.RUNTIME = self._orig
        self._tmp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "SOLAR_DELEGATIONS_DIR": str(self.del_dir),
            "SOLAR_DELEGATIONS_RUNTIME": str(self.runtime),
        }
        return subprocess.run(
            [sys.executable, str(CTL), *args], env=env, text=True, capture_output=True
        )

    @staticmethod
    def payload(proc: subprocess.CompletedProcess) -> dict:
        return json.loads(proc.stdout or proc.stderr)

    def write_events(self, name: str, *records: dict) -> Path:
        path = self.runtime / name / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in records),
            encoding="utf-8",
        )
        return path


class TestMandateChecks(DelegationCtlTestCase):
    def test_status_lists_mandates(self):
        proc = self.cli("status")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("fixture-shadow", proc.stdout)

    def test_shadow_forbids_mutating_action(self):
        proc = self.cli("check", "fixture-shadow", "--action", "run")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(
            any("shadow mode forbids" in e for e in self.payload(proc)["errors"]),
            self.payload(proc),
        )

    def test_shadow_forbids_score_not_in_allowlist(self):
        proc = self.cli("check", "fixture-shadow", "--action", "score")
        self.assertNotEqual(proc.returncode, 0)
        errors = self.payload(proc)["errors"]
        self.assertTrue(any("shadow_safe_actions" in e for e in errors), errors)

    def test_shadow_forbids_resolve_writes(self):
        self.assertNotIn("resolve", delegation_ctl.DEFAULT_SHADOW_SAFE_ACTIONS)
        proc = self.cli("check", "fixture-shadow", "--action", "resolve")
        self.assertNotEqual(proc.returncode, 0)
        errors = self.payload(proc)["errors"]
        self.assertTrue(any("shadow_safe_actions" in e for e in errors), errors)

    def test_shadow_allows_non_mutating_action(self):
        proc = self.cli("check", "fixture-shadow", "--action", "dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(self.payload(proc)["ok"])

    def test_action_outside_allowed_actions_is_refused(self):
        proc = self.cli("check", "fixture-shadow", "--action", "send")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("not in allowed_actions" in e for e in self.payload(proc)["errors"]))

    def test_expired_mandate_is_refused(self):
        proc = self.cli("check", "fixture-expired", "--action", "run")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("expired" in e for e in self.payload(proc)["errors"]))

    def test_incomplete_mandate_is_refused(self):
        errors = delegation_ctl.validate_mandate(self.del_dir / "fixture-incomplete.yaml")
        self.assertTrue(any("missing required" in e for e in errors), errors)

    def test_unknown_mandate_exits_one(self):
        self.assertEqual(self.cli("check", "does-not-exist").returncode, 1)


class TestActivation(DelegationCtlTestCase):
    def test_activate_requires_explicit_approval_flag(self):
        proc = self.cli("activate", "fixture-shadow")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--i-approve", proc.stderr)

    def test_activate_requires_shadow_evidence(self):
        proc = self.cli("activate", "fixture-shadow", "--i-approve")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("shadow evidence" in e for e in self.payload(proc)["errors"]))

    def test_activate_after_shadow_log_then_revoke_blocks_reactivation(self):
        logged = self.cli(
            "shadow-log", "fixture-shadow", "--action", "dry-run", "--details", "plan"
        )
        self.assertEqual(logged.returncode, 0, logged.stderr)
        self.assertFalse(json.loads(logged.stdout)["applied"])

        activated = self.cli("activate", "fixture-shadow", "--i-approve")
        self.assertEqual(activated.returncode, 0, activated.stderr)

        revoked = self.cli("revoke", "fixture-shadow")
        self.assertEqual(revoked.returncode, 0, revoked.stderr)

        proc = self.cli("activate", "fixture-shadow", "--i-approve")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("revoked" in e for e in self.payload(proc)["errors"]))

    def test_activate_rejects_non_json_or_forged_shadow_lines(self):
        path = self.runtime / "fixture-shadow" / "shadow.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "not-json",
                    "",
                    json.dumps(
                        {
                            "mode": "shadow",
                            "applied": True,
                            "intended_action": "dry-run",
                        }
                    ),
                    json.dumps(
                        {
                            "mode": "active",
                            "applied": False,
                            "intended_action": "dry-run",
                        }
                    ),
                    json.dumps(
                        {
                            "mode": "shadow",
                            "applied": False,
                            "intended_action": "send",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        proc = self.cli("activate", "fixture-shadow", "--i-approve")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("valid shadow evidence" in e for e in self.payload(proc)["errors"]))

    def test_shadow_log_rejects_action_outside_allowed_actions(self):
        proc = self.cli(
            "shadow-log", "fixture-shadow", "--action", "send", "--details", "nope"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("not in allowed_actions" in e for e in self.payload(proc)["errors"]))

    def test_shadow_log_refuses_applied_flag_in_shadow_mode(self):
        proc = self.cli(
            "shadow-log",
            "fixture-shadow",
            "--action",
            "dry-run",
            "--details",
            "x",
            "--applied",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any("--applied" in e for e in self.payload(proc)["errors"]))


class TestRuntimeLimits(DelegationCtlTestCase):
    def mandate(self) -> Path:
        return self.del_dir / "fixture-active.yaml"

    def test_cadence_applies_only_to_automated_runs(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write_events(
            "fixture-active", {"ts": recent, "event": "execution_result", "result": "success"}
        )
        automated = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="run", requested_items=1, automated=True
        )
        self.assertTrue(any("frequency limit" in e for e in automated), automated)

        interactive = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="run", requested_items=1
        )
        self.assertEqual(interactive, [])

    def test_unparseable_frequency_fails_closed_when_automated(self):
        path = self.del_dir / "fixture-bad-freq.yaml"
        automated = delegation_ctl.validate_mandate(
            path, for_execute=True, action="run", requested_items=1, automated=True
        )
        self.assertTrue(any("frequency unparseable" in e for e in automated), automated)
        interactive = delegation_ctl.validate_mandate(
            path, for_execute=True, action="run", requested_items=1
        )
        self.assertEqual(interactive, [])

    def test_parse_frequency_days(self):
        self.assertEqual(delegation_ctl.parse_frequency_hours("every 24 hours"), 24)
        self.assertEqual(delegation_ctl.parse_frequency_hours("every 1 day"), 24)
        self.assertIsNone(delegation_ctl.parse_frequency_hours("on-demand or daily when scheduled"))

    def test_stop_conditions_apply_to_non_mutating_actions(self):
        failure = {"ts": "2026-01-01T00:00:00Z", "event": "execution_result", "result": "failure"}
        self.write_events("fixture-active", failure, failure, failure)
        errors = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="score", requested_items=1
        )
        self.assertTrue(any("consecutive failures=3" in e for e in errors), errors)

    def test_consecutive_failures_stop_execution(self):
        failure = {"ts": "2026-01-01T00:00:00Z", "event": "execution_result", "result": "failure"}
        self.write_events("fixture-active", failure, failure, failure)
        errors = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="run", requested_items=1
        )
        self.assertTrue(any("consecutive failures=3" in e for e in errors), errors)

    def test_stop_requested_blocks_execution(self):
        self.write_events("fixture-active", {"ts": "2026-01-01T00:00:00Z", "event": "stop_requested"})
        errors = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="run", requested_items=1
        )
        self.assertTrue(any("stop requested" in e for e in errors), errors)

    def test_daily_volume_rejects_batch_crossing_limit(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        self.write_events(
            "fixture-active",
            {"ts": today, "event": "usage_reserved", "items": 8},
            {"ts": today, "event": "usage_reserved", "items": 10},
        )
        errors = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="run", requested_items=3
        )
        self.assertTrue(any("used=18 requested=3 max=20" in e for e in errors), errors)
        self.assertEqual(
            delegation_ctl.validate_mandate(
                self.mandate(), for_execute=True, action="run", requested_items=2
            ),
            [],
        )

    def test_volume_limited_mandate_requires_items(self):
        errors = delegation_ctl.validate_mandate(
            self.mandate(), for_execute=True, action="run"
        )
        self.assertTrue(any("requires --items" in e for e in errors), errors)

    def test_record_usage_reserves_under_lock_then_refuses(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        self.write_events(
            "fixture-active",
            {"ts": today, "event": "usage_reserved", "items": 18},
        )
        args = SimpleNamespace(name="fixture-active", action="run", items=2, automated=False)
        self.assertEqual(delegation_ctl.cmd_record_usage(args), 0)
        self.assertEqual(
            delegation_ctl.daily_usage(delegation_ctl.runtime_events("fixture-active")), 20
        )
        self.assertEqual(
            delegation_ctl.cmd_record_usage(SimpleNamespace(**{**vars(args), "items": 1})), 2
        )


class TestLiveEvidenceIsUntouched(unittest.TestCase):
    def test_tests_never_write_into_live_shadow_logs(self):
        live = delegation_ctl.WORKSPACE / "sun" / "runtime" / "delegations"
        if not live.exists():
            self.skipTest("no live delegations runtime in this workspace")
        for shadow in live.glob("*/shadow.jsonl"):
            self.assertNotIn(
                "fixture", shadow.read_text(encoding="utf-8"), f"test evidence leaked: {shadow}"
            )


if __name__ == "__main__":
    unittest.main()
