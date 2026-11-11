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
    assert "policy_invalid" in capsys.readouterr().err
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
