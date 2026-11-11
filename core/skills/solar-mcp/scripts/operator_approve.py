"""`solar approve`: the operator's own channel for the four operations that ask for a form.

This is for the human operator on their machine. Agents keep using `solar_execute`; the MCP
form stays the product path and works as before. Use this when the client does not raise the
form (a transport failure, not a policy decision).

    solar approve task.authorize_run <task id or prefix of 8+ characters>
    solar approve async_execution.propose --global-capacity N [--provider-limit NAME=N ...]
    solar approve async_execution.apply
    solar approve telegram.send --chat-id ID --text TEXT [--parse-mode Markdown|HTML]

After the operator types `yes` on an interactive terminal, this command runs the operation
itself. It leaves no grant behind, so no approval id reaches an agent. There is no `--yes`.

Declared limit: a TTY is defence in depth, not a boundary. An agent that has a shell and can
create a pty under the same user could still type `yes`. Do not read more protection into it.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_gate  # noqa: F401  (first: it puts the paths and state scripts on sys.path)
import approval_text
import op_schema
import operations
from mcp_context import OperationError

# The only operations this channel admits. Nothing else is approvable here, task.approve included.
ALLOWED = ("task.authorize_run", "async_execution.propose", "async_execution.apply", "telegram.send")


class Refused(Exception):
    """The command stops before anything runs; the message is for the operator."""


# --------------------------------------------------------------------------
# the terminal
# --------------------------------------------------------------------------

def open_terminal():
    """(read, write, name) of the controlling terminal, or Refused.

    stdin must itself be a terminal: a pipe is refused without reading any confirmation, even when
    /dev/tty exists. The answer is read from /dev/tty, never from stdin."""
    if not sys.stdin.isatty():
        raise Refused("stdin is not an interactive terminal; run this command by hand in a terminal")
    try:
        stream = open("/dev/tty", "r+", encoding="utf-8")
    except OSError:
        raise Refused("there is no controlling terminal (/dev/tty); run this command by hand") from None
    try:
        name = os.ttyname(stream.fileno())
    except OSError:
        name = "/dev/tty"
    return stream, stream, name


def confirm(screen: str, tty_in, tty_out) -> bool:
    """Show exactly what will run; only the word `yes` approves. Anything else, EOF included, declines."""
    tty_out.write(screen.rstrip("\n") + "\n\nType yes to approve; anything else cancels: ")
    tty_out.flush()
    answer = tty_in.readline()
    return answer.strip() == "yes"


# --------------------------------------------------------------------------
# shared checks
# --------------------------------------------------------------------------

def _state():
    """The state layer, or Refused: this channel fails closed when it cannot record what it does."""
    import solar_state

    try:
        with solar_state.read_session():
            pass
    except solar_state.StateError as exc:
        raise Refused(f"the state layer is unavailable ({exc}); nothing was run") from None
    return solar_state


def _validated(name: str, arguments: dict) -> dict:
    if name not in ALLOWED:
        raise Refused(f"{name} is not approvable here. Admitted: {', '.join(ALLOWED)}")
    problem = op_schema.check(arguments, operations.OPERATIONS[name].schema, f"arguments.{name}")
    if problem:
        raise Refused(problem)
    return arguments


def _form_lines(name: str, arguments: dict) -> list[str]:
    """The text the MCP form would show for these arguments, without its countdown footer."""
    body, _title = approval_text.render(name, arguments, seconds=0)
    return body.rsplit("\n\n", 1)[0].split("\n")


def _screen(name: str, extra: list[str], lines: list[str]) -> str:
    return "\n".join(["Operator approval (solar approve): " + name, "", *lines, *extra])


# --------------------------------------------------------------------------
# task.authorize_run
# --------------------------------------------------------------------------

def _facts_from(solar_state, task: dict, context: dict) -> dict:
    """The facts the form renders, from the one read this command makes."""
    values = {key: solar_state.value_of(rest) for key, rest in task["frontmatter"]}
    return dict(title=task["title"] or "", status=task["status"], row_version=task["row_version"],
                values=values, object=task["object"] or "", scope=task["scope"] or "",
                effect=task["effect"] or "",
                recurring=str(values.get("recurring") or "").lower() == "true",
                instructions=context["instructions"].strip("\n").rstrip(), boundary=context["boundary"],
                schedule=approval_text.task_views._schedule(values))


def authorize_run(typed_id: str, tty) -> int:
    solar_state = _state()
    try:
        with solar_state.read_session() as store:
            task_id = store.task_resolve_id(typed_id)
            task = store.task_get(task_id)
            context = store.task_definition_context(task_id)
    except solar_state.StateError as exc:
        raise Refused(str(exc)) from None
    readiness = solar_state.authorization_readiness(task_id, task)
    if not readiness["ready"]:
        raise Refused(f"{readiness['code']}: {readiness['message']}")
    if readiness["execution_authorization"] == "satisfied":
        raise Refused("task_authorization_not_required: " + readiness["message"])

    copy = dict(approval_text.COPY[approval_text.language()], lang=approval_text.language())
    facts = _facts_from(solar_state, task, context)
    pairs = task["frontmatter"]
    digest = solar_state.value_of(next((rest for key, rest in pairs if key == "approved_digest"), None)) or ""
    values = facts["values"]
    lines = [copy["authorize_head"],
             f"Task id: {task_id}",
             *[f"{label}: {value}" for label, value in approval_text._context_rows(copy, facts) if value],
             f"{copy['effect']}: {copy['authorize_effect']}"]
    extra = ["",
             f"Provider / executor: {values.get('provider') or '—'} / {values.get('executor') or 'provider'}",
             f"Run risk: {solar_state.run_risk(pairs)}; not confined because "
             f"{solar_state.unconfined_reason(pairs)}",
             f"Approved digest: {digest[:16]}…  Row version: {facts['row_version']}"]
    if facts["recurring"]:
        extra.append("WARNING: this task is recurring; this authorization covers every repetition "
                     "while its content does not change.")
    stdin, stdout, name = tty
    if not confirm("\n".join(lines + extra), stdin, stdout):
        print("Cancelled: the task is still waiting for authorization.", file=sys.stderr)
        return 1
    try:
        with solar_state.session() as store:
            done = store.task_authorize_run(
                task_id, expected_row_version=facts["row_version"], actor="cli:task.authorize_run",
                channel="cli", tty=name, user=getpass.getuser())
    except solar_state.TaskAuthorizationRefused as exc:
        raise Refused(f"{exc.code}: {exc}") from None
    except solar_state.StateError as exc:
        raise Refused(str(exc)) from None
    print(f"Authorized {task_id} (row_version {done['row_version']}).")
    return 0


# --------------------------------------------------------------------------
# async_execution.propose / apply
# --------------------------------------------------------------------------

def propose(arguments: dict, tty) -> int:
    solar_state = _state()
    _validated("async_execution.propose", arguments)
    try:
        with solar_state.read_session() as store:
            normalized = operations.proposal_document(store.async_policy(), arguments)
    except solar_state.StateError as exc:
        raise Refused(str(exc)) from None
    # The form's own text for these arguments, plus the exact document that will be written.
    shown = _form_lines("async_execution.propose", arguments)
    document = [f"  {line}" for line in solar_state._canonical_json(normalized).replace(",", ",\n").split("\n")]
    stdin, stdout, name = tty
    if not confirm(_screen("async_execution.propose", ["", "Document that will be written:", *document], shown),
                   stdin, stdout):
        print("Cancelled: nothing was written.", file=sys.stderr)
        return 1
    try:
        with solar_state.session() as store:
            path = solar_state.write_proposal(normalized, store.root)
            store.audit_event("async_policy_proposed", actor="cli:async_execution.propose",
                              revision=normalized["revision"], digest=solar_state.policy_digest(normalized),
                              **operations._where("cli", name, getpass.getuser()))
    except solar_state.StateError as exc:
        raise Refused(str(exc)) from None
    print(f"Proposal written to {path} (revision {normalized['revision']}). Nothing was applied.")
    return 0


def apply(tty) -> int:
    solar_state = _state()
    try:
        with solar_state.read_session() as store:
            proposal = solar_state.read_proposal(store.root)
            applied = store.async_policy()
    except solar_state.StateError as exc:
        raise Refused(str(exc)) from None
    if not proposal["present"] or not isinstance(proposal["document"], dict):
        raise Refused("proposal_missing: there is no readable proposal; prepare one with "
                      "`solar approve async_execution.propose`")
    try:
        normalized = solar_state.validate_policy_document(proposal["document"], applied["revision"])
    except solar_state.PolicyInvalid as exc:
        raise Refused(f"policy_invalid: {exc}") from None
    digest = solar_state.policy_digest(normalized)
    arguments = _validated("async_execution.apply", dict(revision=normalized["revision"], proposal_digest=digest))
    # What changes against the policy in force, not only the values in the file.
    changes = [f"  {key}: {applied.get(key)} -> {normalized[key]}"
               for key in ("global_capacity", "provider_capacity", "exclusive_wait_seconds",
                           "enabled_reader_profiles") if applied.get(key) != normalized[key]]
    extra = ["", "Change against the policy in force:", *(changes or ["  (no value changes)"]),
             f"Proposal digest: {digest[:16]}…"]
    stdin, stdout, name = tty
    if not confirm(_screen("async_execution.apply", extra, _form_lines("async_execution.apply", arguments)),
                   stdin, stdout):
        print("Cancelled: nothing was applied.", file=sys.stderr)
        return 1
    try:
        done = operations._do_async_apply(arguments, channel="cli", tty=name, user=getpass.getuser())
    except OperationError as exc:
        raise Refused(f"{exc.code}: {exc}") from None
    except solar_state.StateError as exc:
        raise Refused(str(exc)) from None
    print(f"Applied revision {done['revision']}.")
    return 0


# --------------------------------------------------------------------------
# telegram.send
# --------------------------------------------------------------------------

def telegram_send(arguments: dict, tty) -> int:
    _state()
    _validated("telegram.send", arguments)
    try:
        operations._require_chat(arguments)
    except OperationError as exc:
        raise Refused(f"{exc.code}: {exc}") from None
    stdin, stdout, name = tty
    # External communication: the operator's `yes` is the formal approval of this exact text and chat.
    if not confirm(_screen("telegram.send", [], _form_lines("telegram.send", arguments)), stdin, stdout):
        print("Cancelled: nothing was sent.", file=sys.stderr)
        return 1
    try:
        done = operations._do_telegram_send(arguments, channel="cli", tty=name, user=getpass.getuser())
    except Exception as exc:  # noqa: BLE001 - the shared sender refuses with a plain message
        raise Refused(f"send refused: {exc}") from None
    print(f"Sent to {done['chat_id']}.")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solar approve", description=__doc__.split("\n\n")[0],
                                     epilog="Operator channel: for the human at the terminal. Agents use solar_execute.")
    sub = parser.add_subparsers(dest="operation", required=True, metavar="<operation>")
    run = sub.add_parser("task.authorize_run", help="let a queued, unconfined task run")
    run.add_argument("task", help="task id, or a prefix of at least 8 characters")
    make = sub.add_parser("async_execution.propose", help="write the next async execution configuration")
    make.add_argument("--global-capacity", type=int, required=True)
    make.add_argument("--provider-limit", action="append", default=None, metavar="NAME=N")
    make.add_argument("--exclusive-wait-seconds", type=int)
    make.add_argument("--reader-profile", action="append", default=None, metavar="NAME")
    sub.add_parser("async_execution.apply", help="apply the prepared proposal")
    send = sub.add_parser("telegram.send", help="send one Telegram message")
    send.add_argument("--chat-id", required=True)
    send.add_argument("--text", required=True)
    send.add_argument("--parse-mode", choices=["Markdown", "HTML"])
    return parser


def _proposal_arguments(options) -> dict:
    arguments: dict = dict(global_capacity=options.global_capacity)
    if options.provider_limit is not None:
        limits = []
        for item in options.provider_limit:
            provider, sep, limit = item.partition("=")
            if not sep or not limit.isdigit():
                raise Refused(f"--provider-limit expects NAME=N, got {item!r}")
            limits.append(dict(provider=provider, limit=int(limit)))
        arguments["provider_limits"] = limits
    if options.exclusive_wait_seconds is not None:
        arguments["exclusive_wait_seconds"] = options.exclusive_wait_seconds
    if options.reader_profile is not None:
        arguments["enabled_reader_profiles"] = options.reader_profile
    return arguments


def main(argv: list[str]) -> int:
    options = _parser().parse_args(argv[1:])
    name = options.operation
    if name not in ALLOWED:   # argparse already refuses; kept so the rule reads in one place
        print(f"error: {name} is not approvable here", file=sys.stderr)
        return 2
    try:
        tty = open_terminal()
        if name == "task.authorize_run":
            return authorize_run(options.task, tty)
        if name == "async_execution.propose":
            return propose(_proposal_arguments(options), tty)
        if name == "async_execution.apply":
            return apply(tty)
        arguments = dict(text=options.text, chat_id=options.chat_id)
        if options.parse_mode:
            arguments["parse_mode"] = options.parse_mode
        return telegram_send(arguments, tty)
    except Refused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
