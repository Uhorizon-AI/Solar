"""The notice for a task that waits for authorization, or whose wait ended.

It goes through the task notifier that already exists, to the configured chat only, with the title and
never the instructions, and it does not touch the task. The sender is a double that writes a log; no
chat is reached."""
import os
import subprocess
import time
from pathlib import Path

import pytest

import solar_state
from queue_mirror import env_for

SCRIPTS = Path(__file__).resolve().parents[3] / "skills/solar-async-tasks/scripts"
SECRET = "SECRET-INSTRUCTIONS-MUST-NOT-LEAVE"


def fixture_env(tmp_path):
    workspace = tmp_path / "workspace"
    install = tmp_path / "install"
    sender = install / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.parent.mkdir(parents=True)
    sender.write_text('#!/bin/bash\nprintf "%s|%s\\n" "${TELEGRAM_CHAT_ID:-}" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n')
    sender.chmod(0o755)
    workspace.mkdir()
    (workspace / ".env").write_text("TELEGRAM_CHAT_ID=456\n")
    root = workspace / "sun/runtime/async-tasks"
    root.mkdir(parents=True)
    env = env_for(root, {**os.environ, "SOLAR_WORKSPACE": str(workspace), "SOLAR_ROOT": str(install),
                         "TELEGRAM_CHAT_ID": "456", "TELEGRAM_ALLOWED_CHAT_IDS": "456,999",
                         "TELEGRAM_BOT_TOKEN": "fake"})
    return workspace, root, env


def waiting_task(origin=""):
    fields = [("title", '"Review the thing"')]
    if origin:
        fields.append(("origin_chat_id", f'"{origin}"'))
    with solar_state.session() as store:
        task_id = store.task_create(fields, f"\n# Review the thing\n\n{SECRET}\n")
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
        return task_id, store.task_get(task_id)["row_version"]


def notify(task_id, mode, env):
    return subprocess.run(["bash", str(SCRIPTS / "notify_if_configured.sh"), task_id, mode], env=env,
                          text=True, capture_output=True, timeout=20)


@pytest.mark.parametrize("mode,words", [("--waiting", "Waiting for your approval"),
                                        ("--expired-draft", "back to draft"),
                                        ("--expired-skipped", "skipped")])
def test_each_notice_says_what_happened_and_nothing_else(tmp_path, mode, words):
    workspace, root, env = fixture_env(tmp_path)
    task_id, version = waiting_task()
    done = notify(task_id, mode, env)
    assert done.returncode == 0, done.stderr
    sent = (workspace / "sent.log").read_text()
    assert words in sent and "Review the thing" in sent and sent.startswith("456|")
    assert SECRET not in sent and task_id not in sent
    with solar_state.session() as store:                      # the task is as it was
        assert store.task_get(task_id)["row_version"] == version
        assert "notify_status" not in dict(store.task_get(task_id)["frontmatter"])


def test_it_goes_to_the_configured_chat_never_to_the_one_the_task_names(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task_id, _ = waiting_task(origin="999")                  # allowed, but not the configured chat
    assert notify(task_id, "--waiting", env).returncode == 0
    assert (workspace / "sent.log").read_text().startswith("456|")
    # and the completion notice, which does follow the origin, is unchanged
    assert "999" not in (workspace / "sent.log").read_text()


def test_a_chat_that_is_not_allowed_receives_nothing(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task_id, _ = waiting_task()
    env["TELEGRAM_ALLOWED_CHAT_IDS"] = "111"
    assert notify(task_id, "--waiting", env).returncode == 0
    assert not (workspace / "sent.log").exists()


def test_an_unknown_mode_is_refused_and_sends_nothing(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task_id, _ = waiting_task()
    assert notify(task_id, "--everything", env).returncode == 2
    assert not (workspace / "sent.log").exists()


def test_a_failed_send_reports_failure_and_leaves_the_task_alone(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    sender = Path(env["SOLAR_ROOT"]) / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.write_text("#!/bin/bash\nexit 7\n")
    task_id, version = waiting_task()
    assert notify(task_id, "--waiting", env).returncode == 1
    with solar_state.session() as store:
        assert store.task_get(task_id)["row_version"] == version


# -- the supervisor announces, once ---------------------------------------------------------------

def test_the_supervisor_announces_a_wait_once_however_often_it_polls(rig, tmp_path, monkeypatch):
    install = tmp_path / "install"
    sender = install / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.parent.mkdir(parents=True)
    sender.write_text('#!/bin/bash\nprintf "%s|%s\\n" "${TELEGRAM_CHAT_ID:-}" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n')
    sender.chmod(0o755)
    (rig.workspace / ".env").write_text("TELEGRAM_CHAT_ID=456\n")
    for key, value in (("SOLAR_ROOT", str(install)), ("TELEGRAM_CHAT_ID", "456"),
                       ("TELEGRAM_ALLOWED_CHAT_IDS", "456"), ("TELEGRAM_BOT_TOKEN", "fake")):
        monkeypatch.setenv(key, value)
    task_id = rig.legacy("Needs approval")
    with solar_state.session() as store:                     # as the client flow leaves it
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
    sup = rig.build()
    for _ in range(4):
        sup._fill()
    log = rig.workspace / "sent.log"
    text = log.read_text()
    assert text.count("Waiting for your approval") == 1 and text.startswith("456|") and "Needs approval" in text
    assert rig.status(task_id) == "queued"
    with solar_state.session() as store:
        assert [r["sent"] for r in store.audit_rows("approval_notice_result")] == [True]
