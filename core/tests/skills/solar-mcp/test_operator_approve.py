"""`solar approve`: the operator channel for the four form-gated operations."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import approval_text
import operations
import operator_approve as op
import solar_state
from mcp_helpers import run, stored
from test_telegram_send_gate import stubbed_send  # noqa: F401  (fixture)

SCRIPT = Path(op.__file__)


def work():
    return run("task.create", dict(title="Work", instructions="Approved instructions.", queue=True))


def terminal(monkeypatch, answer="yes\n", during=None):
    """A fake controlling terminal; `during` runs between the screen and the answer."""
    out = io.StringIO()
    monkeypatch.setattr(op, "open_terminal", lambda: (io.StringIO(answer), out, "/dev/ttys999"))
    if during:
        real = op.confirm

        def wrapped(screen, stdin, stdout):
            during()
            return real(screen, stdin, stdout)
        monkeypatch.setattr(op, "confirm", wrapped)
    return out


def audit(event):
    with solar_state.session() as store:
        return store.audit_rows(event)


def execution(task):
    with solar_state.session() as store:
        return store.task_authorization_readiness(task)["execution_authorization"]


def waiting(task):
    return execution(task) != "satisfied"


# -- the terminal --------------------------------------------------------------------------------

def test_without_a_terminal_it_fails_and_runs_nothing(solar_env, monkeypatch, capsys):
    task = work()["id"]
    assert waiting(task)
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))        # not a TTY
    assert op.main(["x", "task.authorize_run", task]) == 1
    assert "not an interactive terminal" in capsys.readouterr().err
    assert waiting(task)


def test_stdin_as_a_pipe_is_refused_without_reading_a_confirmation(solar_env):
    task = work()["id"]
    done = subprocess.run([sys.executable, str(SCRIPT), "task.authorize_run", task], input="yes\n",
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and "not an interactive terminal" in done.stderr
    assert waiting(task)


def test_it_fails_closed_when_the_state_layer_is_unavailable(solar_env, monkeypatch, capsys):
    task = work()["id"]
    terminal(monkeypatch)

    def broken(*args, **kwargs):
        raise solar_state.StateUnavailable("no base")
    monkeypatch.setattr(solar_state, "read_session", broken)
    assert op.main(["x", "task.authorize_run", task]) == 1
    assert "state layer is unavailable" in capsys.readouterr().err


def test_only_the_four_operations_are_admitted(solar_env):
    with pytest.raises(SystemExit) as exc:
        op.main(["x", "task.approve", "whatever"])
    assert exc.value.code == 2
    for name in ("task.approve", "task.create", "action.run"):
        with pytest.raises(op.Refused):
            op._validated(name, {})


# -- task.authorize_run ----------------------------------------------------------------------------

def test_yes_unblocks_a_pending_task_and_records_where_consent_came_from(solar_env, monkeypatch):
    task = work()["id"]
    out = terminal(monkeypatch)
    assert op.main(["x", "task.authorize_run", task[:8]]) == 0          # a prefix, not the full id
    assert execution(task) == "satisfied"
    shown = out.getvalue()
    for needle in (task, "Approved digest", "Row version", "Run risk: high", "Type yes"):
        assert needle in shown
    row = audit("task_run_authorized")[-1]
    assert (row["channel"], row["tty"], row["actor"]) == ("cli", "/dev/ttys999", "cli:task.authorize_run")
    assert row["user"]


@pytest.mark.parametrize("answer", ["no\n", "YES\n", "y\n", ""])
def test_anything_but_yes_leaves_it_pending(solar_env, monkeypatch, answer):
    task = work()["id"]
    terminal(monkeypatch, answer)
    assert op.main(["x", "task.authorize_run", task]) == 1
    assert waiting(task) and not audit("task_run_authorized")


def test_a_task_that_changed_after_it_was_shown_is_rejected(solar_env, monkeypatch, capsys):
    task = work()["id"]

    def edit():
        with solar_state.session() as store:
            store.task_set(task, "effect", '"changed meanwhile"')
    terminal(monkeypatch, during=edit)
    assert op.main(["x", "task.authorize_run", task]) == 1
    assert "task_changed" in capsys.readouterr().err
    assert waiting(task)


def test_a_second_authorization_is_refused_inside_the_transaction(solar_env):
    task = work()["id"]
    with solar_state.session() as store:
        version = store.task_get(task)["row_version"]
        first = store.task_authorize_run(task, expected_row_version=version)
        with pytest.raises(solar_state.TaskAuthorizationRefused) as exc:
            store.task_authorize_run(task, expected_row_version=first["row_version"])
    assert exc.value.code == "task_authorization_not_required"
    assert len(audit("task_run_authorized")) == 1


def test_an_already_authorized_task_is_refused_by_the_command(solar_env, monkeypatch, capsys):
    task = work()["id"]
    terminal(monkeypatch)
    assert op.main(["x", "task.authorize_run", task]) == 0
    terminal(monkeypatch)
    assert op.main(["x", "task.authorize_run", task]) == 1
    assert "task_authorization_not_required" in capsys.readouterr().err


def test_unknown_ambiguous_and_short_prefixes_are_rejected(solar_env):
    for tid in ("abcdefgh-one", "abcdefgh-two"):
        with solar_state.session() as store:
            store.task_import(f'---\nid: "{tid}"\nstatus: draft\ntitle: "T"\n---\n\nBody.\n')
    with solar_state.session() as store:
        assert store.task_resolve_id("abcdefgh-one") == "abcdefgh-one"
        for typed, code in (("abcdefgh", "task_prefix_ambiguous"), ("zzzzzzzz", "task_not_found"),
                            ("abc", "task_prefix_too_short")):
            with pytest.raises(solar_state.TaskPrefixError) as exc:
                store.task_resolve_id(typed)
            assert exc.value.code == code
        assert store.task_resolve_id("abcdefgh-t") == "abcdefgh-two"


# -- async_execution --------------------------------------------------------------------------------

def test_propose_shows_the_document_and_writes_exactly_that(solar_env, monkeypatch):
    out = terminal(monkeypatch)
    assert op.main(["x", "async_execution.propose", "--global-capacity", "3"]) == 0
    with solar_state.session() as store:
        written = solar_state.read_proposal(store.root)["document"]
        assert store.async_policy()["global_capacity"] == 1          # nothing applied
    assert written["global_capacity"] == 3 and '"global_capacity":3' in out.getvalue().replace(" ", "").replace("\n", "")
    row = audit("async_policy_proposed")[-1]
    assert (row["channel"], row["actor"]) == ("cli", "cli:async_execution.propose")


def test_propose_with_invalid_arguments_writes_nothing(solar_env, monkeypatch, capsys):
    terminal(monkeypatch)
    assert op.main(["x", "async_execution.propose", "--global-capacity", "0"]) == 1
    with solar_state.session() as store:
        assert not solar_state.read_proposal(store.root)["present"]


def _propose(monkeypatch, capacity=3):
    terminal(monkeypatch)
    assert op.main(["x", "async_execution.propose", "--global-capacity", str(capacity)]) == 0


def test_apply_shows_the_effective_change_and_applies(solar_env, monkeypatch):
    _propose(monkeypatch)
    out = terminal(monkeypatch)
    assert op.main(["x", "async_execution.apply"]) == 0
    assert "global_capacity: 1 -> 3" in out.getvalue()
    with solar_state.session() as store:
        assert store.async_policy()["global_capacity"] == 3
    row = audit("async_policy_applied")[-1]
    assert (row["channel"], row["actor"]) == ("cli", "cli:async_execution.apply") and row["tty"]


def test_apply_is_rejected_if_the_proposal_changed_after_it_was_shown(solar_env, monkeypatch, capsys):
    _propose(monkeypatch)

    def tamper():
        with solar_state.session() as store:
            document = solar_state.read_proposal(store.root)["document"]
            solar_state.write_proposal(dict(document, global_capacity=4), store.root)
    terminal(monkeypatch, during=tamper)
    assert op.main(["x", "async_execution.apply"]) == 1
    assert "proposal_changed" in capsys.readouterr().err
    with solar_state.session() as store:
        assert store.async_policy()["global_capacity"] == 1


def test_apply_is_rejected_if_the_base_policy_changed_after_it_was_shown(solar_env, monkeypatch, capsys):
    _propose(monkeypatch)

    def move_base():
        with solar_state.session() as store:
            current = store.async_policy()
            store.async_policy_apply(solar_state.validate_policy_document(
                dict(schema_version=solar_state.POLICY_SCHEMA_VERSION, revision=current["revision"] + 1,
                     global_capacity=2, provider_capacity=current["provider_capacity"],
                     exclusive_wait_seconds=current["exclusive_wait_seconds"],
                     enabled_reader_profiles=current["enabled_reader_profiles"]), current["revision"]))
    terminal(monkeypatch, during=move_base)
    assert op.main(["x", "async_execution.apply"]) == 1
    assert "proposal_changed" in capsys.readouterr().err
    with solar_state.session() as store:
        assert store.async_policy()["global_capacity"] == 2


# -- telegram.send -----------------------------------------------------------------------------------

def test_telegram_yes_sends_only_the_displayed_text_to_the_allowed_chat(solar_env, stubbed_send, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    out = terminal(monkeypatch)
    assert op.main(["x", "telegram.send", "--chat-id", "4242", "--text", "hello operator"]) == 0
    sent = json.loads(stubbed_send.read_text())
    assert sent["cmd"][-1] == "hello operator" and sent["chat_id"] == "4242"
    assert "hello operator" in out.getvalue() and "4242" in out.getvalue()
    row = audit("telegram_sent")[-1]
    assert (row["channel"], row["chat_id"]) == ("cli", "4242") and "hello operator" not in json.dumps(row)


def test_telegram_to_a_chat_outside_the_allowed_list_sends_nothing(solar_env, stubbed_send, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    terminal(monkeypatch)
    assert op.main(["x", "telegram.send", "--chat-id", "999", "--text", "hello"]) == 1
    assert not stubbed_send.exists() and "not an allowlisted chat" in capsys.readouterr().err
    assert not audit("telegram_sent")


def test_telegram_declined_sends_nothing(solar_env, stubbed_send, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    terminal(monkeypatch, "no\n")
    assert op.main(["x", "telegram.send", "--chat-id", "4242", "--text", "hello"]) == 1
    assert not stubbed_send.exists()


# -- the MCP path and the screen -------------------------------------------------------------------------

def test_the_mcp_path_records_channel_mcp(solar_env, stubbed_send, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    task = work()["id"]
    version = stored(task)["row_version"]
    run("task.authorize_run", dict(task_id=task, expected_row_version=version))
    run("async_execution.propose", dict(global_capacity=2))
    proposal = solar_state.read_proposal()["document"]
    run("async_execution.apply", dict(revision=proposal["revision"],
                                      proposal_digest=solar_state.policy_digest(proposal)))
    run("telegram.send", dict(text="hi", chat_id="4242"))
    for event in ("task_run_authorized", "async_policy_proposed", "async_policy_applied", "telegram_sent"):
        row = audit(event)[-1]
        assert row["channel"] == "mcp" and "tty" not in row, event


def test_the_screen_carries_every_line_the_mcp_form_shows(solar_env, stubbed_send, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    task = work()["id"]
    version = stored(task)["row_version"]
    cases = [("task.authorize_run", dict(task_id=task, expected_row_version=version),
              ["x", "task.authorize_run", task])]
    cases.append(("telegram.send", dict(text="hello", chat_id="4242"),
                  ["x", "telegram.send", "--chat-id", "4242", "--text", "hello"]))
    cases.append(("async_execution.propose", dict(global_capacity=3),
                  ["x", "async_execution.propose", "--global-capacity", "3"]))
    for name, arguments, argv in cases:
        form, _ = approval_text.render(name, arguments, seconds=60)
        form_lines = form.rsplit("\n\n", 1)[0].split("\n")
        out = terminal(monkeypatch, "no\n")
        op.main(argv)
        screen = out.getvalue().split("\n")
        missing = [line for line in form_lines if line not in screen]
        assert not missing, (name, missing)
    # apply: the same check against a prepared proposal
    _propose(monkeypatch)
    proposal = solar_state.read_proposal()["document"]
    arguments = dict(revision=proposal["revision"], proposal_digest=solar_state.policy_digest(proposal))
    form, _ = approval_text.render("async_execution.apply", arguments, seconds=60)
    out = terminal(monkeypatch, "no\n")
    op.main(["x", "async_execution.apply"])
    assert not [line for line in form.rsplit("\n\n", 1)[0].split("\n") if line not in out.getvalue().split("\n")]


def test_the_old_console_cli_is_gone(solar_env):
    import mcp_approve
    assert not hasattr(mcp_approve, "main") and not hasattr(mcp_approve, "revoke")
    assert callable(mcp_approve.grant) and callable(mcp_approve.listing)
    assert operations.OPERATIONS["task.authorize_run"].authority == "A2"


# -- review follow-ups ---------------------------------------------------------------------------------

def _move_base():
    with solar_state.session() as store:
        current = store.async_policy()
        store.async_policy_apply(solar_state.validate_policy_document(
            dict(schema_version=solar_state.POLICY_SCHEMA_VERSION, revision=current["revision"] + 1,
                 global_capacity=2, provider_capacity=current["provider_capacity"],
                 exclusive_wait_seconds=current["exclusive_wait_seconds"],
                 enabled_reader_profiles=current["enabled_reader_profiles"]), current["revision"]))


def test_apply_is_bound_to_the_base_revision_even_when_the_proposal_is_far_ahead(solar_env, monkeypatch, capsys):
    """A proposal for revision 5 over base 1 must not survive another process applying revision 2."""
    _propose(monkeypatch)
    with solar_state.session() as store:
        document = solar_state.read_proposal(store.root)["document"]
        solar_state.write_proposal(dict(document, revision=5), store.root)
    terminal(monkeypatch, during=_move_base)
    assert op.main(["x", "async_execution.apply"]) == 1
    assert "proposal_changed" in capsys.readouterr().err
    with solar_state.session() as store:
        assert store.async_policy()["revision"] == 1     # only the other process applied


def test_propose_is_refused_if_the_policy_moved_while_the_operator_typed(solar_env, monkeypatch, capsys):
    terminal(monkeypatch, during=_move_base)
    assert op.main(["x", "async_execution.propose", "--global-capacity", "3"]) == 1
    assert "proposal_changed" in capsys.readouterr().err
    with solar_state.session() as store:
        assert not solar_state.read_proposal(store.root)["present"]


def test_a_delivered_message_whose_audit_failed_is_not_reported_as_refused(solar_env, stubbed_send, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    terminal(monkeypatch)

    def broken(*_a, **_k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(solar_state, "session", broken)
    assert op.main(["x", "telegram.send", "--chat-id", "4242", "--text", "hello"]) == 3
    err = capsys.readouterr().err
    assert "Sent to 4242; audit not recorded: disk full" in err and "refused" not in err
    assert stubbed_send.exists()


def test_telegram_checks_the_allowlist_before_asking_for_yes(solar_env, stubbed_send, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "4242")
    out = terminal(monkeypatch)
    assert op.main(["x", "telegram.send", "--chat-id", "999", "--text", "hello"]) == 1
    assert "Type yes" not in out.getvalue()


def test_provider_and_executor_cannot_alter_the_approval_screen(solar_env, monkeypatch):
    task = work()["id"]
    real = op._facts_from

    def hostile(state, task_row, context):
        facts = real(state, task_row, context)
        facts["values"] = dict(facts["values"], provider="x\x1b[2K\rEVIL", executor="y\x1b[31m")
        return facts
    monkeypatch.setattr(op, "_facts_from", hostile)
    out = terminal(monkeypatch, "no\n")
    op.main(["x", "task.authorize_run", task])
    screen = out.getvalue()
    assert "\x1b" not in screen and "\r" not in screen and "\\x1b" in screen


def test_open_terminal_works_on_a_real_pseudo_terminal():
    """The streams are opened for real: a single read/write text stream on a tty is refused by Python."""
    import os
    import pty
    import select

    code = ("import sys; sys.path.insert(0, %r); import operator_approve as o; r, w, n = o.open_terminal(); "
            "w.write('Q: '); w.flush(); print('GOT', r.readline().strip(), flush=True)" % str(SCRIPT.parent))
    import signal
    import time

    pid, fd = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, "-c", code])
    data = b""
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline and b"GOT yes" not in data:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
                if b"Q: " in data and b"GOT" not in data:
                    os.write(fd, b"yes\n")
    finally:
        os.close(fd)
        try:
            os.kill(pid, signal.SIGKILL)      # a child stuck on the terminal must not hang the suite
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
    assert b"GOT yes" in data, data


def test_propose_publishes_under_the_same_write_lock_that_apply_needs(solar_env, monkeypatch):
    """Another process applying a revision cannot land between the check and the published file."""
    import threading

    events, failures = [], []
    started = threading.Event()
    real = solar_state.write_proposal

    def other_process():
        try:
            started.set()
            _move_base()
            events.append("applied")
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            failures.append(exc)

    def racing(document, root=None):
        worker = threading.Thread(target=other_process)
        worker.start()
        assert started.wait(5)
        worker.join(0.5)                 # bounded: an unserialized apply would finish inside this window
        assert worker.is_alive(), "apply ran while the proposal was being published"
        events.append("write")
        path = real(document, root)
        racing.worker = worker
        return path
    monkeypatch.setattr(solar_state, "write_proposal", racing)
    terminal(monkeypatch)
    assert op.main(["x", "async_execution.propose", "--global-capacity", "3"]) == 0
    racing.worker.join(10)
    assert not failures and events == ["write", "applied"]


def test_apply_reads_the_proposal_under_the_write_lock(solar_env, monkeypatch):
    """A proposal replaced while apply waits for the lock must be refused, not applied from a stale read."""
    import threading
    import time

    _propose(monkeypatch)                                       # capacity 3, revision 1
    with solar_state.session() as store:
        document = solar_state.read_proposal(store.root)["document"]
    digest = solar_state.policy_digest(solar_state.validate_policy_document(document, 0))
    arguments = dict(revision=document["revision"], proposal_digest=digest)
    outcome, started = [], threading.Event()

    def apply_it():
        started.set()
        try:
            outcome.append(operations._do_async_apply(arguments, channel="cli", base_revision=0))
        except operations.OperationError as exc:
            outcome.append(exc)

    with solar_state.session() as holder:
        with solar_state._transaction(holder.conn):            # the write lock apply needs
            worker = threading.Thread(target=apply_it)
            worker.start()
            assert started.wait(5)
            time.sleep(0.3)                                     # apply has reached (or passed) its read
            solar_state.write_proposal(dict(document, global_capacity=4), holder.root)
    worker.join(10)
    assert len(outcome) == 1 and getattr(outcome[0], "code", None) == "proposal_changed", outcome
    with solar_state.session() as store:
        assert store.async_policy()["revision"] == 0


def test_a_failure_before_the_file_leaves_the_previous_proposal(solar_env, monkeypatch, capsys):
    _propose(monkeypatch)
    real = solar_state._audit

    def broken(conn, event, **row):
        if event == "async_policy_proposed":
            raise solar_state.StateError("audit down")
        return real(conn, event, **row)
    monkeypatch.setattr(solar_state, "_audit", broken)
    terminal(monkeypatch)
    assert op.main(["x", "async_execution.propose", "--global-capacity", "4"]) == 1
    with solar_state.session() as store:
        assert solar_state.read_proposal(store.root)["document"]["global_capacity"] == 3
    assert len(audit("async_policy_proposed")) == 1


def test_a_failed_commit_after_the_file_is_reported_as_published_not_refused(solar_env, monkeypatch, capsys):
    import sqlite3
    from contextlib import contextmanager

    _propose(monkeypatch)
    real = solar_state._transaction

    @contextmanager
    def failing_commit(conn):
        with real(conn) as inside:
            yield inside
            raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(solar_state, "_transaction", failing_commit)
    terminal(monkeypatch)
    assert op.main(["x", "async_execution.propose", "--global-capacity", "4"]) == 3
    err = capsys.readouterr().err
    assert "published" in err and "not recorded" in err and "refused" not in err
    monkeypatch.setattr(solar_state, "_transaction", real)
    with solar_state.session() as store:
        assert solar_state.read_proposal(store.root)["document"]["global_capacity"] == 4
    assert len(audit("async_policy_proposed")) == 1       # no row for the one that did not commit
