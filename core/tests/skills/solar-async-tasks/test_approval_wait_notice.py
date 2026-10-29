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


def settle(sup, seconds=30):
    """The notices go out on the supervisor's own thread: wait for it, as the loop's next passes would."""
    thread = getattr(sup, "_announcer", None)
    if thread is not None:
        thread.join(seconds)
        assert not thread.is_alive()


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
    assert "999" not in (workspace / "sent.log").read_text()


def test_a_chat_that_is_not_allowed_receives_nothing(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task_id, _ = waiting_task()
    env["TELEGRAM_ALLOWED_CHAT_IDS"] = "111"
    assert notify(task_id, "--waiting", env).returncode == 3          # says it went nowhere
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
        settle(sup)
    log = rig.workspace / "sent.log"
    text = log.read_text()
    assert text.count("Waiting for your approval") == 1 and text.startswith("456|") and "Needs approval" in text
    assert rig.status(task_id) == "queued"
    with solar_state.session() as store:
        assert [r["sent"] for r in store.audit_rows("approval_notice_result")] == [True]


def test_a_missing_sender_fails_without_touching_the_task(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    (Path(env["SOLAR_ROOT"]) / "core/skills/solar-telegram/scripts/send_telegram.sh").unlink()
    task_id, version = waiting_task()
    assert notify(task_id, "--waiting", env).returncode == 1
    with solar_state.session() as store:                      # the client's row_version is still good
        assert store.task_get(task_id)["row_version"] == version
        assert "notify_status" not in dict(store.task_get(task_id)["frontmatter"])


def test_a_failed_notice_is_recorded_and_not_retried(rig, tmp_path, monkeypatch):
    install = tmp_path / "install"
    sender = install / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.parent.mkdir(parents=True)
    sender.write_text('#!/bin/bash\necho run >> "$SOLAR_WORKSPACE/attempts.log"\nexit 7\n')
    sender.chmod(0o755)
    for key, value in (("SOLAR_ROOT", str(install)), ("TELEGRAM_CHAT_ID", "456"),
                       ("TELEGRAM_ALLOWED_CHAT_IDS", "456"), ("TELEGRAM_BOT_TOKEN", "fake")):
        monkeypatch.setenv(key, value)
    task_id = rig.legacy("Needs approval")
    with solar_state.session() as store:
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
    sup = rig.build()
    for _ in range(3):
        sup._fill()
        settle(sup)
    assert (rig.workspace / "attempts.log").read_text().count("run") == 1
    with solar_state.session() as store:
        assert [r["sent"] for r in store.audit_rows("approval_notice_result")] == [False]


def _queue_waiting(rig, title="Needs approval"):
    task_id = rig.legacy(title)
    with solar_state.session() as store:
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
    return task_id


def _sender(tmp_path, monkeypatch, script, chat="456"):
    install = tmp_path / "install"
    sender = install / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.parent.mkdir(parents=True)
    sender.write_text(script)
    sender.chmod(0o755)
    for key, value in (("SOLAR_ROOT", str(install)), ("TELEGRAM_CHAT_ID", chat),
                       ("TELEGRAM_ALLOWED_CHAT_IDS", chat), ("TELEGRAM_BOT_TOKEN", "fake")):
        monkeypatch.setenv(key, value)


def test_a_stuck_sender_never_holds_the_supervisor_and_is_ended_with_its_children(rig, tmp_path, monkeypatch):
    pidfile = tmp_path / "child.pid"
    _sender(tmp_path, monkeypatch, f'#!/bin/bash\nsleep 300 &\necho $! > "{pidfile}"\nwait\n')
    _queue_waiting(rig)
    sup = rig.build()
    sup.NOTIFY_TIMEOUT = 2.0
    started = time.monotonic()
    sup._fill()                                   # the claim finds the wait and the notice starts on its own thread
    assert time.monotonic() - started < 1.5       # a sender that hangs for seconds does not hold the pass
    settle(sup)
    child = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child, 9)
        pytest.fail("the hung sender's child survived the timeout")
    with solar_state.session() as store:
        result = store.audit_rows("approval_notice_result")
        assert [(r["sent"], r["reason"]) for r in result] == [(False, "timeout")]


def test_a_notice_with_nowhere_to_go_is_not_recorded_as_sent(rig, tmp_path, monkeypatch):
    _sender(tmp_path, monkeypatch, "#!/bin/bash\nexit 0\n")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")           # the configured chat is not allowed
    _queue_waiting(rig)
    sup = rig.build()
    for _ in range(2):
        sup._fill()
        settle(sup)
    with solar_state.session() as store:
        result = store.audit_rows("approval_notice_result")
        assert [(r["sent"], r["reason"]) for r in result] == [(False, "not_configured")]


def test_stopping_the_supervisor_ends_a_notice_that_is_still_being_sent(rig, tmp_path, monkeypatch):
    import supervisor_support
    monkeypatch.setattr(supervisor_support.supervisor_mod.Supervisor, "NOTIFY_TIMEOUT", 120.0)
    pidfile = tmp_path / "child.pid"
    _sender(tmp_path, monkeypatch, f'#!/bin/bash\nsleep 300 &\necho $! > "{pidfile}"\nwait\n')
    _queue_waiting(rig)
    with rig.running() as sup:
        supervisor_support.wait_until(pidfile.exists, 30, what="the sender to start")
        child = int(pidfile.read_text())
    # the supervisor has drained: neither its sender nor the thread that waits for it may remain
    thread = getattr(sup, "_announcer", None)
    assert thread is None or not thread.is_alive()
    with solar_state.session() as store:
        result = store.audit_rows("approval_notice_result")
        assert [(r["sent"], r["reason"]) for r in result] == [(False, "supervisor_stopping")]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child, 9)
        pytest.fail("the sender outlived the supervisor")


def test_a_stop_that_lands_after_a_notice_was_taken_starts_no_sender(rig, tmp_path, monkeypatch):
    """The stop falls between the thread taking a notice and starting its sender: the lock decides."""
    _sender(tmp_path, monkeypatch, '#!/bin/bash\necho run >> "$SOLAR_WORKSPACE/attempts.log"\n')
    _queue_waiting(rig)
    sup = rig.build()
    with solar_state.session() as store:
        store.task_claim_next_detail("w")                      # the claim finds the wait; no thread yet
    original = solar_state.Session.approval_notice_claim

    def taken_then_stop(self, ref):
        taken = original(self, ref)
        sup._stop_announcer()                                  # the supervisor starts leaving right now
        return taken

    monkeypatch.setattr(solar_state.Session, "approval_notice_claim", taken_then_stop)
    sup._send_notices()
    assert not (rig.workspace / "attempts.log").exists()       # no sender was started
    with solar_state.session() as store:
        assert store.audit_rows("approval_notice_result") == []          # nothing was tried ...
        assert len(store.audit_rows("approval_notice_released")) == 1
        assert len(store.approval_notices()) == 1                        # ... so the next supervisor sends it


def test_a_closing_supervisor_takes_no_notice_at_all(rig, tmp_path, monkeypatch):
    _sender(tmp_path, monkeypatch, '#!/bin/bash\necho run >> "$SOLAR_WORKSPACE/attempts.log"\n')
    _queue_waiting(rig)
    sup = rig.build()
    with solar_state.session() as store:
        store.task_claim_next_detail("w")
    sup._notice_closing = True
    sup._send_notices()
    assert not (rig.workspace / "attempts.log").exists()
    with solar_state.session() as store:
        assert store.audit_rows("approval_notice") == [] and len(store.approval_notices()) == 1


def test_a_notice_for_a_task_that_is_gone_is_not_sent(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    waiting_task()
    assert notify("no-such-task", "--waiting", env).returncode == 3
    assert not (workspace / "sent.log").exists()


def test_a_notice_without_a_task_id_is_not_sent_and_says_so(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    waiting_task()
    assert notify("", "--waiting", env).returncode == 3
    assert not (workspace / "sent.log").exists()


def test_stopping_the_supervisor_ends_the_failure_notice_it_was_sending(rig, tmp_path, monkeypatch):
    import supervisor_support
    mod = supervisor_support.supervisor_mod
    pidfile = tmp_path / "failure.pid"
    fake = tmp_path / "scripts"
    fake.mkdir()
    (fake / "notify_if_configured.sh").write_text(f'#!/bin/bash\nsleep 300 &\necho $! > "{pidfile}"\nwait\n')
    monkeypatch.setattr(mod, "HERE", fake)
    monkeypatch.setattr(mod.Supervisor, "NOTIFY_TIMEOUT", 120.0)
    sup = rig.build()
    sup._notify_failure("some-task")
    supervisor_support.wait_until(pidfile.exists, 30, what="the failure notice to start")
    child = int(pidfile.read_text())
    sup._stop_announcer()
    assert not sup._failure_sender.is_alive()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and supervisor_support.alive(child):
        time.sleep(0.05)
    assert not supervisor_support.alive(child), "the failure notice outlived the supervisor"
    sup._notify_failure("late-task")                          # after the stop nothing starts
    assert sup._failure_queue.empty()
