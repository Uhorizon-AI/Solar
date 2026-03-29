"""
Black-box contract tests for run_router.py entrypoint.

Calls route() directly (same as the entrypoint does) and validates that
every response conforms to the RouterResponse v3 contract.
"""
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from router import route


V3_TOP_FIELDS = {"status", "request_id", "provider_used", "reply_text", "decision", "error_code", "error"}
V3_DECISION_FIELDS = {"kind", "task_id", "priority_suggested"}
VALID_STATUS = {"success", "failed"}
VALID_KINDS = {"direct_reply", "async_draft_proposal", "async_draft_created", "async_activation_needed"}


def _req(**kwargs):
    base = {
        "request_id": "test",
        "session_id": "sess",
        "user_id": "usr",
        "text": "hello",
        "channel": "other",
        "mode": "direct_only",
    }
    base.update(kwargs)
    return json.dumps(base)


def _assert_valid_v3(tc, result):
    """Assert a result dict is a valid RouterResponse v3."""
    tc.assertIsInstance(result, dict)
    for f in V3_TOP_FIELDS:
        tc.assertIn(f, result, f"missing top-level field: {f}")
    tc.assertIn(result["status"], VALID_STATUS, f"invalid status: {result['status']}")
    decision = result["decision"]
    for f in V3_DECISION_FIELDS:
        tc.assertIn(f, decision, f"missing decision field: {f}")
    tc.assertIn(decision["kind"], VALID_KINDS, f"invalid decision.kind: {decision['kind']}")


# ---------------------------------------------------------------------------
# Contract: every response is a valid v3 dict
# ---------------------------------------------------------------------------

class TestV3ContractOnErrorPaths(unittest.TestCase):
    """All error paths must return a valid v3 dict."""

    def _check(self, raw):
        result = route(raw)
        _assert_valid_v3(self, result)
        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(result["error_code"])
        self.assertIsNotNone(result["error"])
        return result

    def test_missing_stdin(self):
        r = self._check("")
        self.assertEqual(r["error_code"], "missing_input")

    def test_invalid_json(self):
        r = self._check("not-json")
        self.assertEqual(r["error_code"], "invalid_json")

    def test_missing_text(self):
        r = self._check(json.dumps({"request_id": "t", "session_id": "s", "user_id": "u"}))
        self.assertEqual(r["error_code"], "missing_text")

    def test_invalid_mode(self):
        r = self._check(_req(mode="garbage"))
        self.assertEqual(r["error_code"], "invalid_mode")

    def test_unsupported_provider(self):
        r = self._check(_req(provider="notreal"))
        self.assertEqual(r["error_code"], "unsupported_provider")

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": ""})
    def test_async_tasks_disabled(self):
        r = self._check(_req(mode="async_only"))
        self.assertEqual(r["error_code"], "async_tasks_disabled")

    @patch("router.run_strict_provider", side_effect=RuntimeError("lock fail"))
    def test_provider_locked_failed(self, _):
        r = self._check(_req(provider="claude"))
        self.assertEqual(r["error_code"], "provider_locked_failed")

    @patch("router.run_with_fallback", side_effect=RuntimeError("all fail"))
    def test_all_providers_failed(self, _):
        r = self._check(_req())
        self.assertEqual(r["error_code"], "all_providers_failed")


class TestV3ContractOnSuccessPaths(unittest.TestCase):
    """Success paths must return valid v3 dict with status=success."""

    @patch("router.run_with_fallback", return_value=("the response", "claude"))
    def test_direct_only_success(self, _):
        result = route(_req(mode="direct_only"))
        _assert_valid_v3(self, result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertIsNone(result["error_code"])
        self.assertIsNone(result["error"])

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value="task-xyz")
    @patch("router.run_with_fallback", return_value=("async ai body", "claude"))
    def test_async_only_success(self, *_):
        result = route(_req(mode="async_only"))
        _assert_valid_v3(self, result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertEqual(result["decision"]["task_id"], "task-xyz")

    @patch("router.run_with_fallback", return_value=("answer", "gemini"))
    def test_request_id_preserved(self, _):
        result = route(_req(request_id="my-request-id-99"))
        self.assertEqual(result["request_id"], "my-request-id-99")

    @patch("router.run_with_fallback", return_value=("answer", "codex"))
    def test_provider_used_in_response(self, _):
        result = route(_req())
        self.assertEqual(result["provider_used"], "codex")


# ---------------------------------------------------------------------------
# Contract: channel normalization
# ---------------------------------------------------------------------------

class TestChannelNormalization(unittest.TestCase):
    @patch("router.run_with_fallback", return_value=("ok", "claude"))
    def test_unknown_channel_is_normalized(self, _):
        result = route(_req(channel="unknown-channel"))
        self.assertEqual(result["status"], "success")

    @patch("router.run_with_fallback", return_value=("ok", "claude"))
    def test_known_channel_passes(self, _):
        for channel in ("telegram", "n8n", "async-task", "other"):
            with self.subTest(channel=channel):
                result = route(_req(channel=channel))
                self.assertEqual(result["status"], "success")


# ---------------------------------------------------------------------------
# Contract: provider strict mode invariant
# ---------------------------------------------------------------------------

class TestProviderStrictMode(unittest.TestCase):
    @patch("router.run_strict_provider", return_value=("strict response", "claude"))
    def test_provider_override_uses_strict(self, mock_strict):
        result = route(_req(provider="claude"))
        self.assertEqual(result["status"], "success")
        mock_strict.assert_called_once()

    @patch("router.run_with_fallback", return_value=("fallback response", "gemini"))
    def test_no_provider_override_uses_fallback(self, mock_fallback):
        result = route(_req())
        self.assertEqual(result["status"], "success")
        mock_fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
