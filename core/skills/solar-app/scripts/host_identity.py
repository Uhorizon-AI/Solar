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


def pid_file_own_server(pid_file: str) -> bool:
    """True when this runtime's own pid file names a live ``host_server.py``."""
    if not pid_file:
        return False
    try:
        pid = int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if not _pid_alive(pid):
        return False
    return "host_server.py" in pid_command(pid)


def command_is_install_server(command: str, install_roots) -> bool:
    """True when a command line runs ``host_server.py`` from one of these installs.

    ``start_host.sh`` starts the console as
    ``<install>/core/skills/solar-app/scripts/host_server.py``. The absolute
    script path is what makes this precise: a ``host_server.py`` of another
    install is not this runtime's console.

    The path is matched as a substring of the command line, so an install under
    ``Application Support`` (a space in the path) still matches. Both spellings
    of each install are tried — the root as given and its physical form — because
    a console may be started through a symlink (or a ``/var`` vs
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
        wanted.add(canonical(raw) + suffix)
    if not wanted:
        return False
    return any(target in command for target in wanted)


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
        # console on the port would be adopted on an unrelated own pid.
        own = pid_file_own_server(pid_file) and (
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


def _pid_file_pid(pid_file: str):
    """The pid named by a pid file, when it is a live process, else ``None``."""
    if not pid_file:
        return None
    try:
        pid = int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


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
