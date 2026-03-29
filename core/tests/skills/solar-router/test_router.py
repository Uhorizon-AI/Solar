"""
Unit tests for router.py — no real subprocess calls unless mocked.
"""
import json
import unittest
from unittest.mock import patch

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

    def test_empty_returns_unknown(self):
        self.assertEqual(router.sanitize_id("   "), "unknown")


# ---------------------------------------------------------------------------
# strip_solar_metadata + tags
# ---------------------------------------------------------------------------

class TestSolarTags(unittest.TestCase):
    def test_strip_tags(self):
        raw = "Hello\n<solar_decision>direct_reply</solar_decision>\n<solar_summary>x</solar_summary>"
        self.assertEqual(router.strip_solar_metadata(raw), "Hello")

    def test_extract_async_decision(self):
        raw = "Body\n<solar_decision>async_draft_created</solar_decision>\n<solar_summary>s</solar_summary>"
        self.assertEqual(router.extract_tag_decision_kind(raw), "async_draft_created")


# ---------------------------------------------------------------------------
# parse_ai_decision_output (compat for check_router + tooling)
# ---------------------------------------------------------------------------

class TestParseAiDecisionOutput(unittest.TestCase):
    def test_plain_text_degrades(self):
        result = router.parse_ai_decision_output("Plain answer")
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertEqual(result["reply_text"], "Plain answer")
        self.assertTrue(result.get("_degraded"))

    def test_tags_async_in_parse_ai_decision_output(self):
        raw = "Creating task\n<solar_decision>async_draft_created</solar_decision>\n<solar_summary>x</solar_summary>"
        result = router.parse_ai_decision_output(raw)
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertNotIn("solar_", result["reply_text"])
        self.assertFalse(result.get("_degraded"))


# ---------------------------------------------------------------------------
# decision_engine
# ---------------------------------------------------------------------------

class TestDecisionEngine(unittest.TestCase):
    def test_direct_only_always_direct_reply(self):
        result = router.decision_engine("direct_only", "other", "out", "r1", "text")
        self.assertEqual(result["kind"], "direct_reply")

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value="tid")
    def test_async_only_creates_draft(self, _):
        result = router.decision_engine("async_only", "other", "ai out", "r1", "text")
        self.assertEqual(result["kind"], "async_draft_created")
        self.assertEqual(result["task_id"], "tid")

    def test_auto_async_task_channel_direct_reply(self):
        result = router.decision_engine("auto", "async-task", "ignored", "r1", "text")
        self.assertEqual(result["kind"], "direct_reply")

    def test_auto_other_requires_ai_output(self):
        with self.assertRaises(ValueError):
            router.decision_engine("auto", "other", None, "r1", "text")

    def test_auto_telegram_parses_tags(self):
        raw = "ok<solar_decision>async_draft_created</solar_decision><solar_summary>x</solar_summary>"
        result = router.decision_engine("auto", "telegram", raw, "r1", "text")
        self.assertEqual(result["kind"], "async_draft_created")

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            router.decision_engine("unknown_mode", "other", "x", "r1", "text")


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt(unittest.TestCase):
    def test_includes_telegram_routing_hint(self):
        result = router.build_prompt("sys", "hello", "conv1", mode="auto", channel="telegram")
        self.assertIn("telegram", result)
        self.assertIn("solar_decision", result)
        self.assertIn("hello", result)

    def test_direct_only_hint(self):
        result = router.build_prompt("sys", "x", "conv1", mode="direct_only", channel="other")
        self.assertIn("direct_only", result)


# ---------------------------------------------------------------------------
# async_tasks_enabled
# ---------------------------------------------------------------------------

class TestAsyncTasksEnabled(unittest.TestCase):
    def test_enabled_when_feature_present(self):
        with patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks,other"}):
            self.assertTrue(router.async_tasks_enabled())

    def test_disabled_when_absent(self):
        with patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": ""}):
            self.assertFalse(router.async_tasks_enabled())


# ---------------------------------------------------------------------------
# route() — error paths
# ---------------------------------------------------------------------------

def _payload(**kwargs):
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
        self.assertEqual(result["error_code"], "invalid_json")

    def test_missing_text(self):
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


# ---------------------------------------------------------------------------
# route() — success
# ---------------------------------------------------------------------------

class TestRouteSuccessPaths(unittest.TestCase):
    @patch("router.run_with_fallback", return_value=("the answer", "claude"))
    def test_direct_only_success(self, _):
        result = router.route(_payload(mode="direct_only"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["reply_text"], "the answer")
        self.assertEqual(result["decision"]["kind"], "direct_reply")

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value="task-abc-123")
    @patch("router.run_with_fallback", return_value=("async body", "claude"))
    def test_async_only_success(self, *_):
        result = router.route(_payload(mode="async_only"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertEqual(result["decision"]["task_id"], "task-abc-123")

    @patch("router.run_with_fallback")
    def test_auto_telegram_async_tag(self, mock_run):
        raw = (
            "Necesito más tiempo.\n"
            "<solar_decision>async_draft_created</solar_decision>\n"
            "<solar_summary>pendiente confirmación</solar_summary>"
        )
        mock_run.return_value = (raw, "claude")
        result = router.route(
            _payload(mode="auto", channel="telegram", text="haz un informe de 50 paginas")
        )
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertNotIn("solar_decision", result["reply_text"])
        self.assertNotIn("solar_summary", result["reply_text"])

    @patch("router.run_with_fallback", return_value=("hola limpia\n<solar_decision>direct_reply</solar_decision>\n<solar_summary>x</solar_summary>", "claude"))
    def test_auto_n8n_tags_direct_reply(self, _):
        result = router.route(_payload(mode="auto", channel="n8n"))
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertEqual(result["reply_text"], "hola limpia")


# ---------------------------------------------------------------------------
# route_stream
# ---------------------------------------------------------------------------

class TestRouteStream(unittest.TestCase):
    @patch("router.stream_provider")
    def test_done_includes_decision(self, mock_stream):
        mock_stream.return_value = iter([("hola ", "claude"), ("mundo", "claude")])
        payload = _payload(mode="auto", channel="telegram")
        lines = [json.loads(line) for line in router.route_stream(payload)]
        self.assertEqual(lines[0]["type"], "chunk")
        done = lines[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["status"], "success")
        self.assertIn("decision", done)
        self.assertIn("reply_text", done)


if __name__ == "__main__":
    unittest.main()
