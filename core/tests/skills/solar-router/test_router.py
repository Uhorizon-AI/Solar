"""
Unit tests for router.py — no real subprocess calls unless mocked.
"""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

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
    @patch("router.create_async_draft", return_value=("tid", None))
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

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=("tid-gateway", None))
    def test_auto_telegram_parses_tags(self, mock_create):
        raw = "ok<solar_decision>async_draft_created</solar_decision><solar_summary>x</solar_summary>"
        result = router.decision_engine("auto", "telegram", raw, "r1", "text")
        self.assertEqual(result["kind"], "async_draft_created")
        self.assertEqual(result["task_id"], "tid-gateway")
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertTrue(kwargs.get("queue"))
        self.assertTrue(kwargs.get("notify"))

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
        self.assertIn("async_draft_created", result)
        self.assertIn("60 seconds", result)

    def test_direct_only_hint(self):
        result = router.build_prompt("sys", "x", "conv1", mode="direct_only", channel="other")
        self.assertIn("direct_only", result)

    def test_async_task_direct_only_includes_execution_consent(self):
        system_prompt = (
            "## Validation Gate (mandatory)\n"
            "- Task modifies data or sends messages -> wait for approval."
        )
        result = router.build_prompt(
            system_prompt,
            "write the declared artifact",
            "conv1",
            mode="direct_only",
            channel="async-task",
        )
        self.assertIn("Validation Gate", result)
        self.assertIn("already been approved", result)
        self.assertIn("declared artifacts/output paths", result)
        self.assertIn("external sends", result)
        self.assertIn("outside the declared task scope", result)

    def test_includes_recent_turns_when_no_summary(self):
        recent = [
            {"role": "user", "text": "crea el plan"},
            {"role": "assistant", "text": "Propongo Autonomía Supervisada v2"},
        ]
        result = router.build_prompt(
            "sys",
            "Si, crea el plan",
            "conv1",
            mode="direct_only",
            channel="telegram",
            recent=recent,
        )
        self.assertIn("Recent turns", result)
        self.assertIn("Propongo Autonomía Supervisada v2", result)
        self.assertIn("Si, crea el plan", result)

    def test_summary_plus_supplement_turns(self):
        recent = [
            {"role": "user", "text": "Si, crea el plan"},
            {"role": "assistant", "text": "¿Cuál?"},
        ]
        result = router.build_prompt(
            "sys",
            "El plan del mensaje anterior",
            "conv1",
            mode="direct_only",
            channel="telegram",
            recent=recent,
            summary="Pendiente: crear plan Autonomía Supervisada v2 tras aprobación.",
        )
        self.assertIn("Conversation summary", result)
        self.assertIn("Autonomía Supervisada v2", result)
        self.assertIn("Most recent turns", result)
        self.assertNotIn("Recent turns (oldest", result)


# ---------------------------------------------------------------------------
# Conversation continuity (summary + recent turns)
# ---------------------------------------------------------------------------

class TestConversationContinuity(unittest.TestCase):
    def test_extract_summary_from_output(self):
        raw = "Body\n<solar_summary>keep this</solar_summary>"
        self.assertEqual(router.extract_summary_from_output(raw), "keep this")

    def test_load_recent_and_save_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp)
            conv = runtime / "conversations" / "u1.jsonl"
            with patch.object(router, "RUNTIME_ROOT", runtime):
                router.append_message(conv, "user", "hola")
                router.append_message(
                    conv,
                    "assistant",
                    "respuesta\n<solar_summary>ignore in history</solar_summary>",
                )
                recent = router.load_recent_messages(conv)
                self.assertEqual(len(recent), 2)
                self.assertEqual(recent[1]["text"], "respuesta")
                router.save_summary("u1", "rolling context")
                self.assertEqual(router.load_summary("u1"), "rolling context")
                summary, supplement = router.conversation_context("u1", conv)
                self.assertEqual(summary, "rolling context")
                self.assertEqual(len(supplement), 2)

    @patch("router.run_with_fallback")
    def test_route_injects_history_into_prompt(self, mock_run):
        mock_run.return_value = (
            "hecho\n<solar_decision>direct_reply</solar_decision>\n"
            "<solar_summary>plan creado</solar_summary>",
            "claude",
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp)
            conv = runtime / "conversations" / "u.jsonl"
            with patch.object(router, "RUNTIME_ROOT", runtime):
                router.append_message(conv, "user", "analiza Solar")
                router.append_message(
                    conv, "assistant", "Propongo crear Autonomía Supervisada v2"
                )
                result = router.route(
                    _payload(
                        mode="auto",
                        channel="telegram",
                        user_id="u",
                        session_id="u",
                        text="Si, crea el plan",
                    )
                )
                self.assertEqual(result["status"], "success")
                prompt = mock_run.call_args[0][0]
                self.assertIn("Autonomía Supervisada v2", prompt)
                self.assertIn("Si, crea el plan", prompt)
                self.assertEqual(router.load_summary("u"), "plan creado")


# ---------------------------------------------------------------------------
# Codex review hardening (context turns, consent body, notify, ACK)
# ---------------------------------------------------------------------------

class TestParseContextTurns(unittest.TestCase):
    def test_default_when_missing(self):
        self.assertEqual(router.parse_context_turns(None), router.DEFAULT_CONTEXT_TURNS)
        self.assertEqual(router.parse_context_turns(""), router.DEFAULT_CONTEXT_TURNS)
        self.assertEqual(router.parse_context_turns("   "), router.DEFAULT_CONTEXT_TURNS)

    def test_invalid_falls_back(self):
        self.assertEqual(router.parse_context_turns("abc"), router.DEFAULT_CONTEXT_TURNS)
        self.assertEqual(router.parse_context_turns("0"), router.DEFAULT_CONTEXT_TURNS)
        self.assertEqual(router.parse_context_turns("-3"), router.DEFAULT_CONTEXT_TURNS)

    def test_valid_and_cap(self):
        self.assertEqual(router.parse_context_turns("6"), 6)
        self.assertEqual(router.parse_context_turns("12"), 12)
        self.assertEqual(
            router.parse_context_turns(str(router.MAX_CONTEXT_TURNS_CAP + 50)),
            router.MAX_CONTEXT_TURNS_CAP,
        )


class TestGatewayTaskBodyConsent(unittest.TestCase):
    def test_allows_read_analysis_without_reactivation(self):
        body = router._gateway_task_body("analiza el pipeline", "telegram")
        self.assertIn("read/analysis", body.lower())
        self.assertIn("declared artifact", body.lower())
        self.assertIn("without asking to re-activate", body.lower())

    def test_requires_approval_for_mutable_actions(self):
        body = router._gateway_task_body("envía el WhatsApp a Jorge", "n8n")
        self.assertIn("external sends", body.lower())
        self.assertIn("destructive deletes", body.lower())
        self.assertIn("credential", body.lower())
        self.assertIn("execution-consent", body.lower())
        self.assertIn("Validation Gate", body)


class TestGatewayAsyncReply(unittest.TestCase):
    def test_canonical_ack_ignores_model_prose(self):
        reply = router.gateway_async_reply("tid-1")
        self.assertEqual(reply, f"{router.GATEWAY_ASYNC_ACK}\n\n(Tarea: tid-1)")
        self.assertNotIn("¿Quieres", reply)

    def test_includes_notify_warning(self):
        reply = router.gateway_async_reply("tid-2", notify_warning="notify_failed")
        self.assertIn(router.GATEWAY_ASYNC_ACK_NO_NOTIFY, reply)
        self.assertNotIn(router.GATEWAY_ASYNC_ACK, reply)
        self.assertNotIn("Te aviso por aquí cuando termine", reply)
        self.assertNotIn("te aviso manualmente", reply.lower())
        self.assertIn("notify_failed", reply)
        self.assertIn("tid-2", reply)


class TestCreateAsyncDraftNotify(unittest.TestCase):
    @patch("router.subprocess.run")
    @patch("router._resolve_under_home")
    def test_notify_failure_returns_warning(self, mock_resolve, mock_run):
        create_script = MagicMock()
        create_script.is_file.return_value = True
        notify_script = MagicMock()
        notify_script.is_file.return_value = True
        mock_resolve.side_effect = lambda rel: (
            create_script if "create.sh" in rel else notify_script
        )
        mock_run.side_effect = [
            Mock(returncode=0, stdout="ID: task-99\n", stderr=""),
            Mock(returncode=1, stdout="", stderr="boom"),
        ]
        task_id, warning = router.create_async_draft(
            "haz informe",
            "ack",
            "req",
            channel="telegram",
            queue=False,
            notify=True,
        )
        self.assertEqual(task_id, "task-99")
        self.assertEqual(warning, "notify_failed")
        self.assertEqual(mock_run.call_count, 2)

    @patch("router.subprocess.run")
    @patch("router._resolve_under_home")
    def test_notify_script_missing_returns_warning(self, mock_resolve, mock_run):
        create_script = MagicMock()
        create_script.is_file.return_value = True
        notify_script = MagicMock()
        notify_script.is_file.return_value = False
        mock_resolve.side_effect = lambda rel: (
            create_script if "create.sh" in rel else notify_script
        )
        mock_run.return_value = Mock(
            returncode=0, stdout="ID: task-88\n", stderr=""
        )
        task_id, warning = router.create_async_draft(
            "haz informe",
            "ack",
            "req",
            channel="telegram",
            queue=False,
            notify=True,
        )
        self.assertEqual(task_id, "task-88")
        self.assertEqual(warning, "notify_script_missing")
        self.assertEqual(mock_run.call_count, 1)


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

    @patch.dict("os.environ", {"SOLAR_ROUTER_PROVIDER_PRIORITY": "gemini"}, clear=False)
    def test_invalid_provider_priority(self):
        result = router.route(_payload(mode="direct_only"))
        self.assertEqual(result["error_code"], "invalid_provider_priority")
        self.assertIn("gemini", result.get("error", ""))


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
    @patch("router.create_async_draft", return_value=("task-abc-123", None))
    @patch("router.run_with_fallback", return_value=("async body", "claude"))
    def test_async_only_success(self, *_):
        result = router.route(_payload(mode="async_only"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertEqual(result["decision"]["task_id"], "task-abc-123")

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=("task-async-1", None))
    @patch("router.run_with_fallback")
    def test_auto_telegram_async_tag(self, mock_run, mock_create):
        raw = (
            "¿Quieres que lo active y lo pase a queue?\n"
            "<solar_decision>async_draft_created</solar_decision>\n"
            "<solar_summary>informe encolado</solar_summary>"
        )
        mock_run.return_value = (raw, "claude")
        result = router.route(
            _payload(mode="auto", channel="telegram", text="haz un informe de 50 paginas")
        )
        self.assertEqual(result["decision"]["kind"], "async_draft_created")
        self.assertEqual(result["decision"]["task_id"], "task-async-1")
        self.assertNotIn("solar_decision", result["reply_text"])
        self.assertNotIn("solar_summary", result["reply_text"])
        self.assertEqual(
            result["reply_text"],
            router.gateway_async_reply("task-async-1"),
        )
        self.assertNotIn("active", result["reply_text"].lower())
        mock_create.assert_called_once()
        self.assertTrue(mock_create.call_args.kwargs.get("queue"))
        self.assertTrue(mock_create.call_args.kwargs.get("notify"))

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=("task-n8n-1", None))
    def test_resolve_decision_n8n_queues_and_acks(self, mock_create):
        raw = (
            "¿Lo activo?\n"
            "<solar_decision>async_draft_created</solar_decision>\n"
            "<solar_summary>x</solar_summary>"
        )
        decision, reply = router.resolve_decision(
            "auto", "n8n", raw, "crea un plan largo", "req-1"
        )
        self.assertEqual(decision["kind"], "async_draft_created")
        self.assertEqual(decision["task_id"], "task-n8n-1")
        self.assertEqual(reply, router.gateway_async_reply("task-n8n-1"))
        self.assertTrue(mock_create.call_args.kwargs.get("queue"))
        self.assertTrue(mock_create.call_args.kwargs.get("notify"))

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=("task-warn-1", "notify_failed"))
    def test_resolve_decision_surfaces_notify_warning(self, _):
        raw = (
            "Me pongo con ello.\n"
            "<solar_decision>async_draft_created</solar_decision>\n"
            "<solar_summary>x</solar_summary>"
        )
        decision, reply = router.resolve_decision(
            "auto", "telegram", raw, "auditoria larga", "req-warn"
        )
        self.assertEqual(decision["task_id"], "task-warn-1")
        self.assertIn("notify_failed", reply)
        self.assertIn(router.GATEWAY_ASYNC_ACK_NO_NOTIFY, reply)
        self.assertNotIn(router.GATEWAY_ASYNC_ACK, reply)

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=(None, None))
    def test_async_only_telegram_create_failure_falls_back(self, mock_create):
        decision, reply = router.resolve_decision(
            "async_only",
            "telegram",
            "ignored",
            "haz un informe enorme",
            "req-fail",
        )
        self.assertEqual(decision["kind"], "direct_reply")
        self.assertIsNone(decision["task_id"])
        self.assertIn("could not create the async task", reply)
        self.assertNotEqual(reply, router.GATEWAY_ASYNC_ACK)
        self.assertNotIn(router.GATEWAY_ASYNC_ACK, reply)
        mock_create.assert_called_once()

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=(None, None))
    @patch("router.run_with_fallback", return_value=("async body", "claude"))
    def test_async_only_telegram_route_create_failure(self, *_):
        result = router.route(
            _payload(mode="async_only", channel="telegram", text="informe largo")
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["decision"]["kind"], "direct_reply")
        self.assertIsNone(result["decision"]["task_id"])
        self.assertIn("could not create the async task", result["reply_text"])
        self.assertNotIn(router.GATEWAY_ASYNC_ACK, result["reply_text"])

    @patch.dict("os.environ", {"SOLAR_SYSTEM_FEATURES": "async-tasks"})
    @patch("router.create_async_draft", return_value=("draft-other-1", None))
    def test_resolve_decision_other_creates_draft_not_queued(self, mock_create):
        raw = (
            "Draft listo.\n"
            "<solar_decision>async_draft_created</solar_decision>\n"
            "<solar_summary>x</solar_summary>"
        )
        decision, reply = router.resolve_decision(
            "auto", "other", raw, "haz un informe", "req-2"
        )
        self.assertEqual(decision["kind"], "async_draft_created")
        self.assertEqual(decision["task_id"], "draft-other-1")
        self.assertFalse(mock_create.call_args.kwargs.get("queue"))
        self.assertFalse(mock_create.call_args.kwargs.get("notify"))
        self.assertIn("draft-other-1", reply)

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


# ---------------------------------------------------------------------------
# _provider_priority (agy migration / no silent fallback)
# ---------------------------------------------------------------------------

class TestProviderPriority(unittest.TestCase):
    def setUp(self):
        # Provider parsing tests do not exercise the one-time workspace bridge.
        router._ENV_AGY_MIGRATION_ATTEMPTED = True

    def test_legacy_workspace_is_atomically_healed_once(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = pathlib.Path(td)
            env_path = workspace / ".env"
            env_path.write_text(
                "SOLAR_ROUTER_PROVIDER_PRIORITY=gemini,codex\n",
                encoding="utf-8",
            )
            router._ENV_AGY_MIGRATION_ATTEMPTED = False
            with (
                patch.object(router, "SOLAR_WORKSPACE", workspace),
                patch.dict(
                    "os.environ",
                    {
                        "SOLAR_ROUTER_PROVIDER_PRIORITY": "gemini,codex",
                        "SOLAR_AI_PROVIDER_PRIORITY": "",
                    },
                    clear=False,
                ),
            ):
                self.assertEqual(router._provider_priority(), ["agy", "codex"])
            self.assertIn(
                "SOLAR_ROUTER_PROVIDER_PRIORITY=agy,codex",
                env_path.read_text(encoding="utf-8"),
            )

    def test_failed_workspace_heal_can_retry_in_same_process(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = pathlib.Path(td)
            (workspace / ".env").write_text(
                "SOLAR_ROUTER_PROVIDER_PRIORITY=gemini,codex\n",
                encoding="utf-8",
            )
            router._ENV_AGY_MIGRATION_ATTEMPTED = False
            failed = router.subprocess.CompletedProcess(
                args=["migrator"],
                returncode=1,
                stdout="",
                stderr="temporary write failure",
            )
            with (
                patch.object(router, "SOLAR_WORKSPACE", workspace),
                patch.object(router.subprocess, "run", return_value=failed),
                patch.dict(
                    "os.environ",
                    {"SOLAR_ROUTER_PROVIDER_PRIORITY": "gemini,codex"},
                    clear=False,
                ),
            ):
                with self.assertRaises(router.UnsupportedProviderPriorityError):
                    router._provider_priority()
            self.assertFalse(router._ENV_AGY_MIGRATION_ATTEMPTED)

    def test_valid_priority(self):
        with patch.dict("os.environ", {"SOLAR_ROUTER_PROVIDER_PRIORITY": "codex,claude"}, clear=False):
            self.assertEqual(router._provider_priority(), ["codex", "claude"])

    def test_legacy_gemini_raises_clear_error(self):
        with patch.dict("os.environ", {"SOLAR_ROUTER_PROVIDER_PRIORITY": "gemini"}, clear=False):
            with self.assertRaises(router.UnsupportedProviderPriorityError) as ctx:
                router._provider_priority()
            msg = str(ctx.exception)
            self.assertIn("gemini", msg)
            self.assertIn("agy", msg)
            self.assertIn("unsupported provider", msg)

    def test_gemini_mixed_with_valid_still_raises(self):
        with patch.dict(
            "os.environ",
            {"SOLAR_ROUTER_PROVIDER_PRIORITY": "codex,gemini"},
            clear=False,
        ):
            with self.assertRaises(router.UnsupportedProviderPriorityError) as ctx:
                router._provider_priority()
            self.assertIn("gemini", str(ctx.exception))

    def test_empty_after_invalid_only_raises(self):
        with patch.dict(
            "os.environ",
            {"SOLAR_ROUTER_PROVIDER_PRIORITY": "not-a-provider"},
            clear=False,
        ):
            with self.assertRaises(router.UnsupportedProviderPriorityError) as ctx:
                router._provider_priority()
            self.assertIn("unsupported provider", str(ctx.exception))

    def test_whitespace_only_raises(self):
        with patch.dict("os.environ", {"SOLAR_ROUTER_PROVIDER_PRIORITY": " , , "}, clear=False):
            with self.assertRaises(router.UnsupportedProviderPriorityError) as ctx:
                router._provider_priority()
            self.assertIn("no supported providers", str(ctx.exception))

    def test_default_priority(self):
        with patch.dict(
            "os.environ",
            {
                "SOLAR_ROUTER_PROVIDER_PRIORITY": "",
                "SOLAR_AI_PROVIDER_PRIORITY": "",
            },
            clear=False,
        ):
            self.assertEqual(
                router._provider_priority(),
                ["codex", "claude", "agy", "agent"],
            )


if __name__ == "__main__":
    unittest.main()
