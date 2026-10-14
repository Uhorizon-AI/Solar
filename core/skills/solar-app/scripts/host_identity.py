#!/usr/bin/env python3
"""Single policy for console identity.

One decision point for every reuse path: is the console that answered this
runtime's own? ``check_host.sh``, ``host_lib.sh`` (listener identity and orphan
stopping), ``start_host.sh`` and ``stop_host.sh`` all reach this module, so the
rules cannot drift apart.

Identity is compared on physical paths (``expanduser`` + ``resolve``), never on
the string received: a workspace opened through a symlink and the same
workspace opened by its real path are one identity.

A console that reports no identity at all — or only half of it — is adopted only
when this runtime can prove the process is its own: its own pid file names a
live ``host_server.py``, or the listener's command line is a ``host_server.py``
of this install (the legacy console from before ``/health`` reported a
``runtime``).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def canonical(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _pid_alive(pid: int) -> bool:
    """True when the pid exists.

    ``os.kill(pid, 0)`` raises ``PermissionError`` (a subclass of ``OSError``)
    when the process is alive but owned by another user. That is still "alive":
    it is reported alive, and the command-line check that follows decides whether
    it is ours (it never is, for another user's process).
    """
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def pid_command(pid: int) -> str:
    """The `ps` command line of a pid, or "" when it cannot be read."""
    try:
        shown = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return shown.stdout or ""


def _pid_file_pid(pid_file: str):
    """The pid named by a pid file, when it is a live process, else ``None``."""
    if not pid_file:
        return None
    try:
        pid = int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def pid_file_own_server(pid_file: str, pid=None) -> bool:
    """True when this runtime's own pid file names a live ``host_server.py``.

    ``pid`` is the value already resolved by :func:`_pid_file_pid`: a caller that
    needs the pid too passes it in, so the file is read once and cannot change
    between the two reads.
    """
    if not pid_file:
        return False
    if pid is None:
        pid = _pid_file_pid(pid_file)
    if pid is None:
        return False
    return "host_server.py" in pid_command(pid)


def _path_end_is_clean(command: str, end: int) -> bool:
    """True when nothing extends the path past ``end`` (a boundary or the end)."""
    return end >= len(command) or command[end].isspace() or command[end] in "'\""


def _interpreted_script(prefix: str) -> bool:
    """True when the text before a script path ends at an interpreter boundary.

    The console is the script the command executes, so the word before the path
    must be a ``python*`` interpreter (its flags skipped), or the command must be
    the script itself. Anything else means the path is a mere argument.
    """
    prefix = prefix.rstrip().rstrip("'\"")
    if not prefix:
        return True
    tokens = prefix.split()
    while tokens and tokens[-1].startswith("-"):
        tokens.pop()
    if not tokens:
        return False
    return "python" in Path(tokens[-1].strip("'\"")).name


def command_is_install_server(command: str, install_roots) -> bool:
    """True when a command line runs ``host_server.py`` from one of these installs.

    ``start_host.sh`` runs ``python3 -u <install>/core/skills/solar-app/scripts/host_server.py``.
    The absolute script path is what makes this precise: a ``host_server.py`` of
    another install is not this runtime's console. The path must be the word the
    interpreter executes — a file that merely mentions the path as an argument
    (``python3 otro.py .../host_server.py``) is not this runtime's console.

    Both spellings of each install are tried — the root as given and its physical
    form — because a console may be started through a symlink (or a ``/var`` vs
    ``/private/var`` temporary directory).
    """
    if not command or "host_server.py" not in command:
        return False
    suffix = "/core/skills/solar-app/scripts/host_server.py"
    wanted = set()
    for root in install_roots:
        if not root:
            continue
        raw = root.rstrip("/")
        wanted.add(raw + suffix)
        wanted.add(canonical(raw + suffix))
    if not wanted:
        return False
    # Exact spelling first: this is the only branch that handles a path with a
    # space ("Application Support"), because it needs no tokenisation.
    for target in wanted:
        start = command.find(target)
        if start >= 0 and _path_end_is_clean(command, start + len(target)) \
                and _interpreted_script(command[:start]):
            return True
    # Fallback for a symlinked spelling (/var vs /private/var): slice the path at
    # the whitespace before it, which is safe because this branch never carries a
    # path with a space.
    idx = command.find(suffix)
    while idx >= 0:
        start = idx
        while start > 0 and command[start - 1] not in " \t'\"":
            start -= 1
        candidate = command[start:idx + len(suffix)]
        if canonical(candidate) in wanted and _interpreted_script(command[:start]):
            return True
        idx = command.find(suffix, idx + 1)
    return False


def evaluate(*, health, workspace, runtime, pid_file="", listener_pid="",
             listener_command="", install_roots=()):
    """Return ``None`` when the console is this runtime's own, else a reason.

    ``health`` is the parsed ``/health`` payload. ``pid_file``,
    ``listener_command`` and ``listener_pid`` are the independent proofs that the
    process is ours; any one is enough for a console that reports no identity or
    only half of it. ``listener_command`` is only read when the health payload is
    incomplete, so a healthy console never costs a ``ps`` call; when it is empty
    and ``listener_pid`` is set, the command line is resolved on demand.

    A pid file only proves ownership of the pid it names. When ``listener_pid``
    is also known, it must be the same process: a foreign console on the port
    would otherwise be adopted because an unrelated own pid is alive.
    """
    got_ws = str((health or {}).get("workspace") or "")
    got_rt = str((health or {}).get("runtime") or "")
    if got_ws and canonical(got_ws) != canonical(workspace):
        return "another workspace (" + got_ws + ")"
    if got_rt and canonical(got_rt) != canonical(runtime):
        return "another runtime (" + got_rt + ")"
    if got_ws and got_rt:
        return None
    own = False
    pid_file_pid = _pid_file_pid(pid_file)
    if pid_file_pid is not None:
        # The pid file must name a live host_server.py, and — when the port's
        # listener is known — it must be that very process. Otherwise a foreign
        # console on the port would be adopted on an unrelated own pid. The pid
        # already resolved is passed in, so the file is read only once.
        own = pid_file_own_server(pid_file, pid=pid_file_pid) and (
            not listener_pid or str(pid_file_pid) == str(listener_pid).strip()
        )
    if not own:
        command = listener_command
        if not command and listener_pid:
            try:
                command = pid_command(int(str(listener_pid).strip()))
            except ValueError:
                command = ""
        own = command_is_install_server(command, install_roots)
    if own:
        return None
    if not got_ws and not got_rt:
        return "a console with no identity and no process of this runtime"
    return (
        "a console with partial identity (workspace=" + (got_ws or "-")
        + " runtime=" + (got_rt or "-") + ") and no process of this runtime"
    )


def _load_health(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Console identity policy.")
    # dest is "subcommand", not "command": the
    # command-is-install-server subparser has a --command option, and a shared
    # name would let that option overwrite the subcommand selector.
    sub = parser.add_subparsers(dest="subcommand", required=True)

    check = sub.add_parser("evaluate", help="Decide whether a console is this runtime's own.")
    check.add_argument("--health-file", required=True)
    check.add_argument("--workspace", required=True)
    check.add_argument("--runtime", required=True)
    check.add_argument("--pid-file", default="")
    check.add_argument("--listener-command", default="")
    check.add_argument("--listener-pid", default="")
    check.add_argument("--install-root", action="append", default=[])

    own = sub.add_parser("pid-file-is-own-server", help="Is the pid file a live host_server.py?")
    own.add_argument("--pid-file", required=True)

    cmd = sub.add_parser("command-is-install-server",
                         help="Does a command line run this install's host_server.py?")
    cmd.add_argument("--command", required=True)
    cmd.add_argument("--install-root", action="append", default=[])

    args = parser.parse_args(argv)
    if args.subcommand == "pid-file-is-own-server":
        return 0 if pid_file_own_server(args.pid_file) else 1
    if args.subcommand == "command-is-install-server":
        return 0 if command_is_install_server(args.command, args.install_root) else 1

    reason = evaluate(
        health=_load_health(args.health_file),
        workspace=args.workspace,
        runtime=args.runtime,
        pid_file=args.pid_file,
        listener_pid=args.listener_pid,
        listener_command=args.listener_command,
        install_roots=args.install_root,
    )
    if reason is None:
        print("ok")
        return 0
    print("mismatch: " + reason)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
