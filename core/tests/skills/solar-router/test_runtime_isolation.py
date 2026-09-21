"""The router suite must never write into the live runtime store.

The 11/09 verification of the storage move found this suite appending to the
machine's real `router/audit.jsonl` and rewriting `continuity/active.json`:
25 runs with `request_id: "test"` landed in the record the console reads and the
SQLite index projects. These tests fix the wall that `conftest.isolated_runtime`
puts up, so a regression fails here instead of in someone's operational history.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from router import route
import router


def _live_runtime_candidates() -> list[Path]:
    """The two homes that must stay untouched, resolved without the fixture env."""
    homes = []
    if sys.platform == "darwin":
        homes.append(Path.home() / "Library" / "Application Support" / "Solar" / "runtime")
    else:
        homes.append(Path.home() / ".local" / "share" / "Solar" / "runtime")
    # core/tests/skills/solar-router/ -> workspace that holds planets/<planet>/
    workspace = Path(__file__).resolve().parents[5]
    homes.append(workspace / "sun" / "runtime")
    return homes


def _fingerprint(path: Path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


class TestRuntimeIsolation(unittest.TestCase):
    """Path containment: deterministic, no dependency on what the machine does."""

    @pytest.fixture(autouse=True)
    def _runtime(self, isolated_runtime):
        self.runtime = isolated_runtime

    def test_router_writes_inside_the_fixture(self):
        self.assertTrue(str(router.RUNTIME_ROOT).startswith(str(self.runtime.root)))
        self.assertTrue(
            str(router.continuity_root()).startswith(str(self.runtime.root)))

    def test_router_does_not_point_at_any_live_runtime(self):
        for live in _live_runtime_candidates():
            for used in (Path(router.RUNTIME_ROOT), Path(router.continuity_root())):
                self.assertFalse(
                    str(used.resolve()).startswith(str(live.resolve())) if live.exists()
                    else str(used).startswith(str(live)),
                    f"router would write under the live store: {used} ⊂ {live}")

    @patch("router.run_with_fallback", return_value=("the response", "claude"))
    def test_a_real_route_lands_in_the_fixture_and_nowhere_else(self, _):
        live = [(path, _fingerprint(path)) for path in
                [home / "router" / "audit.jsonl" for home in _live_runtime_candidates()]
                + [home / "continuity" / "active.json" for home in _live_runtime_candidates()]]

        request = json.dumps({
            "request_id": "isolation-check", "session_id": "sess", "user_id": "usr",
            "text": "hello", "channel": "other", "mode": "direct_only",
        })
        result = route(request)
        self.assertEqual(result["status"], "success")

        # The writes happened — in the fixture.
        self.assertTrue(self.runtime.audit.exists(), "the fixture audit was never written")
        events = [json.loads(line) for line in
                  self.runtime.audit.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(any(row.get("event") == "start" for row in events))
        self.assertTrue(any(row.get("event") == "end" for row in events))
        self.assertTrue(self.runtime.continuity.exists(),
                        "the fixture continuity record was never written")

        # And the live store did not move.
        for path, before in live:
            self.assertEqual(_fingerprint(path), before,
                             f"the live runtime store was written: {path}")

    def test_the_fixture_starts_empty_for_each_test(self):
        """No leak between tests: a previous test's audit must not be visible."""
        self.assertFalse(self.runtime.audit.exists())


class TestEnvironmentRedirect(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _runtime(self, isolated_runtime):
        self.runtime = isolated_runtime

    def test_env_points_at_the_fixture_for_subprocesses(self):
        for name in ("SOLAR_RUNTIME_ROOT", "SOLAR_RUNTIME_DIR",
                     "SOLAR_ROUTER_RUNTIME_DIR", "SOLAR_DELEGATIONS_RUNTIME",
                     "SOLAR_APP_DATA"):
            value = os.environ.get(name, "")
            self.assertTrue(value, f"{name} is not set by the fixture")
            self.assertNotIn("Application Support/Solar/runtime", value)
            self.assertFalse(value.endswith("/Solar/sun/runtime"))

    def test_workspace_redirect_is_in_process_not_exported(self):
        """Exporting it would break every test that shells out (fail-closed resolver)."""
        self.assertEqual(Path(router.SOLAR_WORKSPACE), self.runtime.workspace)
        self.assertNotEqual(os.environ.get("SOLAR_WORKSPACE", ""),
                            str(self.runtime.workspace))
