"""
Unit tests for router.py — no real subprocess calls.
PROVIDERS are mocked via patch so no AI binaries are needed.
"""
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import router


# ---------------------------------------------------------------------------
# parse_request_payload
# ---------------------------------------------------------------------------

class TestParseRequestPayload(unittest.TestCase):
    def test_valid_json(self):
        result = router.parse_request_payload('{"a": 1}')
        self.assertEqual(result["a"], 1)

    def test_invalid_json_raises(self):
        with self.assertRaises(Exception):
            router.parse_request_payload("not json")

    def test_empty_raises(self):
        with self.assertRaises(Exception):
            router.parse_request_payload("")


# ---------------------------------------------------------------------------
# sanitize_id
# ---------------------------------------------------------------------------

class TestSanitizeId(unittest.TestCase):
    def test_clean_value(self):
        self.assertEqual(router.sanitize_id("user123"), "user123")

    def test_special_chars_replaced(self):
        result = router.sanitize_id("user@domain.com/path")
        self.assertNotIn("@", result)
        self.assertNotIn("/", result)

    def test_empty_returns_unknown(self):
        self.assertEqual(router.sanitize_id("   "), "unknown")

    def test_truncates_at_120(self):
        result = router.sanitize_id("a" * 200)
        self.assertEqual(len(result), 120)


# ---------------------------------------------------------------------------
# parse_ai_decision_output
# ---------------------------------------------------------------------------

class TestParseAiDecisionOutput(unittest.TestCase):
    def test_valid_json_with_decision(self):
        import json
        payload = json.dumps({"decision": {"kind": "direct_reply"}, "reply_text": "hi"})
        result = router.parse_ai_decision_output(payload)
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertEqual(result["reply_text"], "hi")

    def test_json_with_code_fences(self):
        import json
        payload = "```json\n" + json.dumps({"decision": {"kind": "async_draft_created"}, "reply_text": "ok"}) + "\n```"
        result = router.parse_ai_decision_output(payload)
        self.assertEqual(result["decision"]["kind"], "async_draft_created")

    def test_json_embedded_in_text(self):
        import json
        block = json.dumps({"decision": {"kind": "direct_reply"}, "reply_text": "sure"})
        raw = f"Some preamble\n{block}\nSome suffix"
        result = router.parse_ai_decision_output(raw)
        self.assertEqual(result["decision"]["kind"], "direct_reply")

    def test_plain_text_degrades_to_direct_reply(self):
        result = router.parse_ai_decision_output("This is a plain text response")
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertEqual(result["reply_text"], "This is a plain text response")
        self.assertTrue(result.get("_degraded"))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            router.parse_ai_decision_output("")

    def test_whitespace_raises(self):
        with self.assertRaises(ValueError):
            router.parse_ai_decision_output("   ")


# ---------------------------------------------------------------------------
# decision_engine
# ---------------------------------------------------------------------------

class TestDecisionEngine(unittest.TestCase):
    def test_direct_only_always_direct_reply(self):
        result = router.decision_engine("direct_only", "other", None, "r1", "text")
        self.assertEqual(result["kind"], "direct_reply")

    def test_async_only_returns_async_draft_created(self):
        result = router.decision_engine("async_only", "other", None, "r1", "text")
        self.assertEqual(result["kind"], "async_draft_created")

    def test_auto_async_task_channel_always_direct_reply(self):
        result = router.decision_engine("auto", "async-task", "ignored", "r1", "text")
        self.assertEqual(result["kind"], "direct_reply")

    def test_auto_other_channel_requires_ai_output(self):
        with self.assertRaises(ValueError):
            router.decision_engine("auto", "other", None, "r1", "text")

    def test_auto_parses_ai_output(self):
        import json
        ai = json.dumps({"decision": {"kind": "async_draft_created"}, "reply_text": "ok"})
        result = router.decision_engine("auto", "telegram", ai, "r1", "text")
        self.assertEqual(result["kind"], "async_draft_created")

    def test_auto_invalid_kind_falls_back_to_direct_reply(self):
        import json
        ai = json.dumps({"decision": {"kind": "made_up_kind"}, "reply_text": "ok"})
        result = router.decision_engine("auto", "other", ai, "r1", "text")
        self.assertEqual(result["kind"], "direct_reply")

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            router.decision_engine("unknown_mode", "other", None, "r1", "text")


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt(unittest.TestCase):
    def test_mode_auto_includes_json_instruction(self):
        result = router.build_prompt("sys", [], "hello", "conv1", "auto", "other")
        self.assertIn("JSON", result)
        self.assertIn("decision", result)

    def test_mode_direct_does_not_include_json_instruction(self):
        result = router.build_prompt("sys", [], "hello", "conv1", "direct_only", "other")
        self.assertNotIn("decision", result)
        self.assertIn("Respond directly", result)

    def test_includes_conversation_context(self):
        result = router.build_prompt("sys", [], "hello", "myconv", "auto", "telegram")
        self.assertIn("myconv", result)
        self.assertIn("telegram", result)

    def test_includes_recent_turns(self):
        recent = [{"role": "user", "text": "prev"}, {"role": "assistant", "text": "resp"}]
        result = router.build_prompt("sys", recent, "now", "c", "direct_only", "other")
        self.assertIn("USER: prev", result)
        self.assertIn("ASSISTANT: resp", result)

    def test_includes_jit_agent_role(self):
        jit = {"agent_content": "# Role: tester\nTest things.", "skills_content": [], "jit_generated": False, "planet": None}
        result = router.build_prompt("sys", [], "hello", "c", "direct_only", "other", jit)
        self.assertIn("Agent Role", result)
        self.assertIn("tester", result)

    def test_includes_skills_catalog(self):
        jit = {
            "agent_content": None,
            "skills_content": [{"name": "solar-router", "description": "Routes AI requests"}],
            "jit_generated": True,
            "planet": None,
        }
        result = router.build_prompt("sys", [], "hello", "c", "direct_only", "other", jit)
        self.assertIn("solar-router", result)
        self.assertIn("Routes AI requests", result)


# ---------------------------------------------------------------------------
# async_tasks_enabled
# ---------------------------------------------------------------------------

class TestAsyncTasksEnabled(unittest.TestCase):
    def test_enabled_when_feature_present(self):
        with patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks,other"}):
            self.assertTrue(router.async_tasks_enabled())

    def test_disabled_when_feature_absent(self):
        with patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": ""}, clear=False):
            import importlib
            # Reload to pick up fresh env — or call directly
            self.assertFalse(router.async_tasks_enabled())

    def test_disabled_when_env_missing(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "SOLAR_SYSTEM_FEATURES"}
        with patch.dict("os.environ", env, clear=True):
            self.assertFalse(router.async_tasks_enabled())


# ---------------------------------------------------------------------------
# route() — all error paths, no real subprocess
# ---------------------------------------------------------------------------

def _payload(**kwargs):
    import json
    base = {
        "request_id": "t",
        "session_id": "s",
        "user_id": "u",
        "text": "hello",
        "channel": "other",
        "mode": "direct_only",
    }
    base.update(kwargs)
    return json.dumps(base)


class TestRouteErrorPaths(unittest.TestCase):
    def test_missing_input(self):
        result = router.route("")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "missing_input")

    def test_invalid_json(self):
        result = router.route("not-json")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "invalid_json")

    def test_missing_text(self):
        import json
        result = router.route(json.dumps({"request_id": "t", "session_id": "s", "user_id": "u", "channel": "other", "mode": "auto"}))
        self.assertEqual(result["error_code"], "missing_text")

    def test_invalid_mode(self):
        result = router.route(_payload(mode="bad_mode"))
        self.assertEqual(result["error_code"], "invalid_mode")

    def test_unsupported_provider(self):
        result = router.route(_payload(provider="fakeai"))
        self.assertEqual(result["error_code"], "unsupported_provider")

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": ""})
    def test_async_tasks_disabled(self):
        result = router.route(_payload(mode="async_only"))
        self.assertEqual(result["error_code"], "async_tasks_disabled")

    @patch("router.run_strict_provider", side_effect=RuntimeError("boom"))
    def test_provider_locked_failed(self, _):
        result = router.route(_payload(mode="direct_only", provider="claude"))
        self.assertEqual(result["error_code"], "provider_locked_failed")

    @patch("router.run_with_fallback", side_effect=RuntimeError("all dead"))
    def test_all_providers_failed(self, _):
        result = router.route(_payload(mode="direct_only"))
        self.assertEqual(result["error_code"], "all_providers_failed")


class TestRouteSuccessPaths(unittest.TestCase):
    @patch("router.run_with_fallback", return_value=("the answer", "claude"))
    def test_direct_only_success(self, _):
        result = router.route(_payload(mode="direct_only"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["reply_text"], "the answer")
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertEqual(result["provider_used"], "claude")

    @patch("router.run_strict_provider", return_value=("strict answer", "claude"))
    def test_direct_only_with_provider_override(self, _):
        result = router.route(_payload(mode="direct_only", provider="claude"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider_used"], "claude")

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value="task-abc-123")
    def test_async_only_success(self, _):
        result = router.route(_payload(mode="async_only"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertEqual(result["decision"]["task_id"], "task-abc-123")

    @patch("router.run_with_fallback", return_value=("response", "gemini"))
    def test_response_has_required_v3_fields(self, _):
        result = router.route(_payload(mode="direct_only"))
        for field in ("status", "request_id", "provider_used", "reply_text", "decision", "error_code", "error"):
            self.assertIn(field, result, f"missing field: {field}")
        for field in ("kind", "task_id", "priority_suggested"):
            self.assertIn(field, result["decision"], f"missing decision field: {field}")

    @patch("router.run_with_fallback", return_value=("response", "claude"))
    def test_unknown_channel_normalized_to_other(self, _):
        result = router.route(_payload(mode="direct_only", channel="unknown_channel"))
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
