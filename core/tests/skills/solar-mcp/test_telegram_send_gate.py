"""Sending Telegram is a verb with the same gate as creating a task.

Nothing here reaches Telegram. `send_telegram.sh` is replaced by a stub that
records what it was handed, so the assertions are about the gate and about where
the token came from — never about a real message.

The corte this covers: the token stopped living in the workspace, so the only
route an agent has to Telegram is this tool, and this tool refuses without an
approval Louis granted out of band.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import mcp_approve
import mcp_gate
import mcp_server
from mcp_gate import A0, A2, A3, A4


def registry(**overrides):
    reg = dict(mcp_server.TOOLS)
    reg["_action_skills"] = {}
    reg.update(overrides)
    return reg


@pytest.fixture
def stubbed_send(solar_env, monkeypatch, tmp_path):
    """A fake sender and a fake store, so a send never leaves the machine."""
    store = tmp_path / "secrets" / "installation.env"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("TELEGRAM_BOT_TOKEN=fixture-token\n", encoding="utf-8")
    monkeypatch.setenv("SOLAR_SECRETS_FILE", str(store))

    # Visible configuration, where it still belongs: the workspace.
    (solar_env.workspace / ".env").write_text(
        "TELEGRAM_CHAT_ID=4242\nTELEGRAM_PARSE_MODE=Markdown\n", encoding="utf-8")

    recorded = tmp_path / "sent.json"

    def fake_run(cmd, **kwargs):
        recorded.write_text(json.dumps(dict(
            cmd=[str(part) for part in cmd],
            token=kwargs.get("env", {}).get("TELEGRAM_BOT_TOKEN"),
            chat_id=kwargs.get("env", {}).get("TELEGRAM_CHAT_ID"),
            parse_mode=kwargs.get("env", {}).get("TELEGRAM_PARSE_MODE"),
            cwd=kwargs.get("cwd"),
        )), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "OK: message sent", "")

    monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)
    import solar_secrets
    import importlib
    importlib.reload(solar_secrets)
    return recorded


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def test_sending_without_an_approval_is_refused(solar_env):
    verdict = mcp_gate.preflight("solar_telegram_send", {"text": "hola"}, registry())
    assert not verdict.allowed
    assert verdict.code == "approval_required"
    assert verdict.authority == A2
    assert "sends outside the machine" in verdict.reason


def test_a_client_cannot_approve_its_own_send(solar_env):
    for forged in ({"approved": True}, {"authority": "A2"}, {"external": "ok"},
                   {"approval_id": ""}, {"approval_id": "deadbeef"}):
        verdict = mcp_gate.preflight(
            "solar_telegram_send", {"text": "hola", **forged}, registry())
        assert not verdict.allowed, forged


def test_the_approval_is_bound_to_the_exact_text(solar_env):
    granted = mcp_approve.grant("solar_telegram_send", {"text": "hola"}, 900, "test")
    swapped = mcp_gate.preflight(
        "solar_telegram_send",
        {"text": "otra cosa", "approval_id": granted["approval_id"]}, registry())
    assert not swapped.allowed
    assert swapped.code == "approval_scope_mismatch"

    exact = mcp_gate.preflight(
        "solar_telegram_send",
        {"text": "hola", "approval_id": granted["approval_id"]}, registry())
    assert exact.allowed and exact.code == "approval_ok"


@pytest.mark.parametrize("authority", [A0, A3, A4])
def test_external_communication_is_refused_at_any_other_authority(solar_env, authority):
    """A2 in front of a human is the only shape an outbound send may take."""
    reg = registry(solar_telegram_send=dict(
        **{**mcp_server.TOOLS["solar_telegram_send"], "authority": authority}))
    verdict = mcp_gate.preflight("solar_telegram_send", {"text": "hola"}, reg)
    assert not verdict.allowed
    assert verdict.code == "external_communication_refused"


def test_the_tool_declares_what_it_is(solar_env):
    spec = mcp_server.TOOLS["solar_telegram_send"]
    assert spec["authority"] == A2
    assert spec["external_communication"] is True
    # The catalog has to name the send: an agent reading tools/list must find it.
    assert "Telegram" in spec["description"]


# --------------------------------------------------------------------------
# where the token comes from
# --------------------------------------------------------------------------

def test_the_send_uses_the_process_store_not_the_workspace(solar_env, stubbed_send):
    result = mcp_server._do_telegram_send({"text": "hola"})
    assert result["sent"] is True
    handed = json.loads(stubbed_send.read_text(encoding="utf-8"))
    assert handed["token"] == "fixture-token"
    assert handed["chat_id"] == "4242"
    assert handed["cmd"][-1] == "hola"
    assert handed["cmd"][1].endswith("send_telegram.sh")


def test_a_token_in_the_workspace_does_not_reach_the_sender(solar_env, stubbed_send):
    """Belt and braces: even a `.env` that still carries one is ignored."""
    (solar_env.workspace / ".env").write_text(
        "TELEGRAM_CHAT_ID=4242\nTELEGRAM_BOT_TOKEN=leftover-in-the-workspace\n",
        encoding="utf-8")
    mcp_server._do_telegram_send({"text": "hola"})
    handed = json.loads(stubbed_send.read_text(encoding="utf-8"))
    assert handed["token"] == "fixture-token"


def test_a_stray_key_in_the_store_reaches_nothing(solar_env, stubbed_send, tmp_path):
    """The handler loads the allowlist, not the file.

    Whatever else ends up in that file — by accident, by an old migration, by
    someone editing it — does not enter the environment the sender inherits.
    """
    store = Path(os.environ["SOLAR_SECRETS_FILE"])
    trace = tmp_path / "executed"
    store.write_text(
        "TELEGRAM_BOT_TOKEN=fixture-token\n"
        f"EVIL=$(touch {trace})\n"
        "TELEGRAM_CHAT_ID=9999\n",
        encoding="utf-8")

    mcp_server._do_telegram_send({"text": "hola"})
    assert not trace.exists()
    handed = json.loads(stubbed_send.read_text(encoding="utf-8"))
    assert handed["token"] == "fixture-token"
    # TELEGRAM_CHAT_ID is not an installation secret: the workspace still owns it,
    # so the store cannot redirect a send to another chat.
    assert handed["chat_id"] == "4242"


def test_without_a_store_there_is_nothing_to_send_with(solar_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SOLAR_SECRETS_FILE", str(tmp_path / "absent.env"))
    (solar_env.workspace / ".env").write_text("TELEGRAM_CHAT_ID=4242\n", encoding="utf-8")
    import solar_secrets
    import importlib
    importlib.reload(solar_secrets)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        mcp_server._do_telegram_send({"text": "hola"})


def test_a_chat_outside_the_allowlist_is_refused(solar_env, stubbed_send):
    with pytest.raises(RuntimeError, match="not an allowlisted chat"):
        mcp_server._do_telegram_send({"text": "hola", "chat_id": "999"})
    assert not stubbed_send.exists()


def test_a_named_allowlist_widens_it(solar_env, stubbed_send, monkeypatch):
    (solar_env.workspace / ".env").write_text(
        "TELEGRAM_CHAT_ID=4242\nTELEGRAM_ALLOWED_CHAT_IDS=4242, 777\n", encoding="utf-8")
    mcp_server._do_telegram_send({"text": "hola", "chat_id": "777"})
    assert json.loads(stubbed_send.read_text(encoding="utf-8"))["chat_id"] == "777"


# --------------------------------------------------------------------------
# the script the runtime calls
# --------------------------------------------------------------------------

def test_send_telegram_refuses_when_the_token_is_only_in_dot_env(solar_env, tmp_path):
    """The route the harness used to have: a `.env` next to the chat, and a send.

    The script no longer takes the token from the file, so that route is closed
    even if a token is put back there.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=123:abc\nTELEGRAM_CHAT_ID=4242\n", encoding="utf-8")
    script = Path(mcp_server._SKILLS) / "solar-telegram" / "scripts" / "send_telegram.sh"

    env = {k: v for k, v in os.environ.items()
           if k not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
    proc = subprocess.run(["bash", str(script), "hola"], capture_output=True,
                          text=True, cwd=str(workspace), env=env)
    assert proc.returncode == 1
    assert "Missing required key: TELEGRAM_BOT_TOKEN" in proc.stdout
    assert "solar_telegram_send" in proc.stdout
