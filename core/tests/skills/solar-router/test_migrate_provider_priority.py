"""Unit tests for migrate_provider_priority.py."""
from __future__ import annotations

import pathlib
import sys
import unittest

_SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "skills" / "solar-router" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from migrate_provider_priority import migrate_priority_csv  # noqa: E402


class TestMigratePriorityCsv(unittest.TestCase):
    def test_gemini_alone(self):
        migrated, changed = migrate_priority_csv("gemini")
        self.assertEqual(migrated, "agy")
        self.assertTrue(changed)

    def test_gemini_duplicate(self):
        migrated, changed = migrate_priority_csv("gemini,gemini")
        self.assertEqual(migrated, "agy")
        self.assertTrue(changed)

    def test_mixed_duplicates(self):
        migrated, changed = migrate_priority_csv("codex,gemini,gemini,claude")
        self.assertEqual(migrated, "codex,agy,claude")
        self.assertTrue(changed)

    def test_case_insensitive(self):
        migrated, changed = migrate_priority_csv("GEMINI,codex")
        self.assertEqual(migrated, "agy,codex")
        self.assertTrue(changed)

    def test_noop_canonical(self):
        migrated, changed = migrate_priority_csv("codex,claude,agy")
        self.assertEqual(migrated, "codex,claude,agy")
        self.assertFalse(changed)

    def test_whitespace_and_empty(self):
        migrated, changed = migrate_priority_csv(" codex , , gemini , ")
        self.assertEqual(migrated, "codex,agy")
        self.assertTrue(changed)

    def test_full_default_noop(self):
        migrated, changed = migrate_priority_csv("codex,claude,agy,agent")
        self.assertEqual(migrated, "codex,claude,agy,agent")
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
