"""Unit tests for validate_mcp.py (agy multipath)."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "skills" / "solar-browser" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import validate_mcp as vm  # noqa: E402


def _ok_entry() -> dict:
    return {
        "command": "npx",
        "args": [
            "-y",
            "chrome-devtools-mcp@latest",
            "--browserUrl",
            "http://127.0.0.1:9222",
        ],
    }


class TestAgyMultipath(unittest.TestCase):
    def test_local_and_global_both_listed_local_effective(self):
        with tempfile.TemporaryDirectory() as td:
            ws = pathlib.Path(td) / "ws"
            home = pathlib.Path(td) / "home"
            local = ws / ".agents" / "mcp_config.json"
            global_cfg = home / ".gemini" / "antigravity-cli" / "mcp_config.json"
            local.parent.mkdir(parents=True)
            global_cfg.parent.mkdir(parents=True)
            payload = {"mcpServers": {"chrome-devtools": _ok_entry()}}
            local.write_text(json.dumps(payload), encoding="utf-8")
            global_cfg.write_text(json.dumps(payload), encoding="utf-8")

            targets = vm.agy_existing_targets(home, ws)
            names = [t[0] for t in targets]
            self.assertIn("agy/local", names)
            self.assertIn("agy/antigravity-cli", names)
            local_row = next(t for t in targets if t[0] == "agy/local")
            self.assertTrue(local_row[3], "local should be effective")
            global_row = next(t for t in targets if t[0] == "agy/antigravity-cli")
            self.assertFalse(global_row[3])

    def test_legacy_settings_only_if_mcp_servers(self):
        with tempfile.TemporaryDirectory() as td:
            ws = pathlib.Path(td) / "ws"
            home = pathlib.Path(td) / "home"
            ws.mkdir()
            settings = home / ".gemini" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
            self.assertEqual(vm.agy_existing_targets(home, ws), [])

            settings.write_text(
                json.dumps({"mcpServers": {"chrome-devtools": _ok_entry()}}),
                encoding="utf-8",
            )
            targets = vm.agy_existing_targets(home, ws)
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0][0], "agy/legacy-settings")

    def test_default_priority_fallback_includes_agent(self):
        self.assertEqual(vm.DEFAULT_PRIORITY_FALLBACK, "codex,claude,agy,agent")
        raw, ordered = vm.parse_router_priority({})
        self.assertEqual(raw, "codex,claude,agy,agent")
        self.assertEqual(ordered, ["codex", "claude", "agy", "agent"])

    def test_main_validates_both_paths(self):
        with tempfile.TemporaryDirectory() as td:
            ws = pathlib.Path(td) / "ws"
            home = pathlib.Path(td) / "home"
            local = ws / ".agents" / "mcp_config.json"
            global_cfg = home / ".gemini" / "config" / "mcp_config.json"
            local.parent.mkdir(parents=True)
            global_cfg.parent.mkdir(parents=True)
            good = {"mcpServers": {"chrome-devtools": _ok_entry()}}
            bad = {
                "mcpServers": {
                    "chrome-devtools": {
                        "command": "npx",
                        "args": ["wrong"],
                    }
                }
            }
            local.write_text(json.dumps(good), encoding="utf-8")
            global_cfg.write_text(json.dumps(bad), encoding="utf-8")
            (ws / ".env").write_text(
                "SOLAR_ROUTER_PROVIDER_PRIORITY=agy\n",
                encoding="utf-8",
            )

            with patch.object(sys, "argv", ["validate_mcp.py", "--repo-root", str(ws), "--home", str(home)]):
                code = vm.main()
            self.assertEqual(code, 1)  # global drift


if __name__ == "__main__":
    unittest.main()
