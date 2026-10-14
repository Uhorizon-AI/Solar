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
import re
import subprocess
import sys
from pathlib import Path


def canonical(path: str) -> str:
    return str(Path(path).expanduser().resolve())


# The interpreter that runs the console: ``python``, ``python3.12``, the macOS
# ``Python`` (Python.app), a universal-build ``python3.12-intel64`` and the
# Windows ``pythonw``. The platform suffix is restricted to the architecture
# tags a real build carries, so a wrapper named ``python-my-tool`` or a helper
# named ``python3-config`` is not mistaken for the interpreter.
_PYTHON_INTERPRETER = re.compile(
    r"python(?:w|[\d.]*(?:-(?:intel64|arm64|universal2))?)?", re.IGNORECASE)

# Flags that take their value as the next argv token (``-X dev``, ``-W ignore``).
# They must be skipped together with that value, or the value looks like the
# interpreter name and an own console is misread as foreign.
_FLAGS_WITH_VALUE = ("-X", "-W", "-Q", "--check-hash-based-pycs")


def _pid_alive(pid: int) -> bool:
    """True when the pid exists.

    ``os.kill(pid, 0)`` raises ``PermissionError`` (a subclass of ``OSError``)
    when the process is alive but owned by another user. That is still "alive":
    it is reported alive, and the command-line check that follows decides whether
    it is ours (it never is, for another user's process).

    A pid ``<= 0`` is refused before the syscall: ``os.kill(0, 0)`` signals the
    caller's whole process group and ``os.kill(-1, 0)`` every process it may
    signal, so both would report "alive" without naming a process.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
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


def port_listener_pids(port) -> list:
    """Every pid listening on ``port`` in numeric order, or ``[]`` when none.

    The same ``lsof`` query the shell does, exposed here so a caller can resolve
    the listeners lazily: it runs only when the identity payload is incomplete.
    Returning the whole list lets a caller accept a pid that is not the first,
    which is what makes the pid-file proof and the port sweep agree.
    """
    try:
        shown = subprocess.run(
            ["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    # Numeric order, not text order ("10000" must not come before "999"), the
    # same rule `solar_host_port_listener_pids` applies with `sort -n -u`, so the
    # two implementations return the identical list for the same lsof output.
    # Non-numeric lines (an lsof warning on stdout) are skipped, never a
    # ValueError.
    return sorted(
        {line.strip() for line in (shown.stdout or "").splitlines() if line.strip().isdigit()},
        key=int,
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


def pid_file_own_server(pid_file: str, pid=None) -> bool:
    """True when this runtime's own pid file names a live ``host_server.py``.

    ``pid`` is the value already resolved by :func:`_pid_file_pid`: a caller that
    needs the pid too passes it in, so the file is read once and cannot change
    between the two reads. When it is provided, the path is not required.
    """
    if pid is None:
        if not pid_file:
            return False
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
    must be a ``python`` interpreter (its flags skipped), or the command must be
    the script itself. A binary whose name merely contains "python"
    (``ipython-wrapper``, ``python-my-tool``) is not the interpreter.

    The name is matched case-insensitively and with the platform suffixes an
    interpreter really carries: macOS runs it as ``Python`` (Python.app), a
    universal build as ``python3.12-intel64``, and Windows ships ``pythonw``.
    Interpreter flags between the name and the script are allowed, including the
    ones that take a separate value (``python3 -X dev <script>``).
    """
    prefix = prefix.rstrip().rstrip("'\"")
    if not prefix:
        return True
    tokens = [token.strip("'\"") for token in prefix.split()]
    # The interpreter is the last token that is one, and everything after it must
    # be flags (with their values) — otherwise the "interpreter" is really an
    # earlier argument and the script is executed by something else.
    for index in range(len(tokens) - 1, -1, -1):
        name = Path(tokens[index]).name
        if not _PYTHON_INTERPRETER.fullmatch(name):
            continue
        if _only_flags_follow(tokens[index + 1:]):
            return True
    return False


def _only_flags_follow(tokens) -> bool:
    """True when every token is an interpreter flag (and its value, if any)."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return False
        if token in _FLAGS_WITH_VALUE:
            index += 2
        else:
            index += 1
    return True


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


def evaluate(*, health, workspace, runtime, pid_file="", listener_pids=(),
             listener_command="", install_roots=()):
    """Return ``None`` when the console is this runtime's own, else a reason.

    ``health`` is the parsed ``/health`` payload. ``pid_file``,
    ``listener_command`` and ``listener_pids`` are the independent proofs that
    the process is ours; any one is enough for a console that reports no identity
    or only half of it. ``listener_command`` is only read when the health payload
    is incomplete, so a healthy console never costs a ``ps`` call; when it is
    empty and ``listener_pids`` is set, the command lines are resolved on demand
    from each listener. Both ``listener_pids`` and the pid file are read only
    when the payload turns out incomplete: the supervisor's frequent path pays for
    neither.

    ``listener_pids`` may be a callable, resolved at most once and only when the
    payload is incomplete, so a healthy console never pays for ``lsof``.

    A pid file only proves ownership of the pid it names. When the port's
    listeners are known, that pid must be one of them: a foreign console on the
    port would otherwise be adopted because an unrelated own pid is alive. The
    whole list is compared, not just its first pid: with several listeners, a
    valid pid beyond the first must still be accepted.
    """
    got_ws = str((health or {}).get("workspace") or "")
    got_rt = str((health or {}).get("runtime") or "")
    # A relative path (an old console) cannot be compared: `resolve()` would
    # anchor it to the verifier's cwd and report a false "another workspace".
    # A non-absolute path is treated as no identity at all.
    if got_ws and not Path(got_ws).expanduser().is_absolute():
        got_ws = ""
    if got_rt and not Path(got_rt).expanduser().is_absolute():
        got_rt = ""
    if got_ws and canonical(got_ws) != canonical(workspace):
        return "another workspace (" + got_ws + ")"
    if got_rt and canonical(got_rt) != canonical(runtime):
        return "another runtime (" + got_rt + ")"
    if got_ws and got_rt:
        return None

    listeners = listener_pids() if callable(listener_pids) else listener_pids
    listeners = [str(pid).strip() for pid in (listeners or []) if str(pid).strip()]

    own = False
    pid_file_pid = _pid_file_pid(pid_file)
    if pid_file_pid is not None:
        # One rule for both branches: the pid file's process must be this
        # install's own host_server.py. ``pid_file_own_server`` alone only checks
        # the "host_server.py" substring, so a reused pid running another
        # install's server would be adopted; the install-level proof is required
        # whether or not the port's listeners could be enumerated.
        pid_file_own = pid_file_own_server("", pid=pid_file_pid) and command_is_install_server(
            pid_command(pid_file_pid), install_roots
        )
        if listeners:
            # The pid file must name a live host_server.py, and it must be one of
            # the port's listeners. A pid that is not the first listener is still
            # a listener.
            own = pid_file_own and str(pid_file_pid) in listeners
        else:
            # No listener could be enumerated (lsof missing or timed out). The
            # pid file alone only proves runtime membership, which would let a
            # foreign console on the port be adopted on an unrelated own pid, so
            # the install-level proof above is what carries the decision.
            own = pid_file_own
    if not own:
        own = command_is_install_server(listener_command, install_roots)
    if not own and listeners:
        # Try every listener: the first pid on the port is not necessarily the
        # server, so a single `ps` on listeners[0] would make the answer depend on
        # numeric pid order.
        for pid in listeners:
            try:
                command = pid_command(int(pid))
            except (ValueError, OSError):
                continue
            if command_is_install_server(command, install_roots):
                own = True
                break
    if own:
        return None
    if not got_ws and not got_rt:
        return "a console with no identity and no process of this runtime"
    return (
        "a console with partial identity (workspace=" + (got_ws or "-")
        + " runtime=" + (got_rt or "-") + ") and no process of this runtime"
    )


def pid_file_names_listener(pid_file: str, wanted, install_roots=()) -> bool:
    """True when the pid file names ``wanted`` and that pid is this install's server.

    One implementation for the shell's hung-listener path: the file must hold
    exactly the pid under test, and that pid must run this install's own
    ``host_server.py``. A pid file of another process proves nothing, and a
    ``host_server.py`` of another install is not this runtime's console.
    """
    try:
        held = Path(pid_file).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return False
    if not wanted or held != str(wanted).strip():
        return False
    if not pid_file_own_server("", pid=_pid_file_pid(pid_file)):
        return False
    return command_is_install_server(pid_command(int(held)), install_roots)


def _load_health(path: str) -> dict:
    """The parsed ``/health`` payload, or ``{}`` when it cannot be read.

    A missing, unreadable or malformed file is not a crash: the policy decides
    what a console with no usable identity is, and it must still print its
    ``mismatch:`` line instead of a traceback.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
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
    check.add_argument("--listener-pids", default="",
                       help="Comma- or newline-separated listeners the caller already resolved.")
    check.add_argument("--listener-command", default="")
    check.add_argument("--port", default="",
                       help="Resolve the listeners with lsof only if the payload is incomplete.")
    check.add_argument("--install-root", action="append", default=[])

    own = sub.add_parser("pid-file-is-own-server", help="Is the pid file a live host_server.py?")
    own.add_argument("--pid-file", required=True)

    names = sub.add_parser("pid-file-names-listener",
                           help="Does the pid file name this install's listener?")
    names.add_argument("--pid-file", required=True)
    names.add_argument("--pid", required=True)
    names.add_argument("--install-root", action="append", default=[])

    cmd = sub.add_parser("command-is-install-server",
                         help="Does a command line run this install's host_server.py?")
    cmd.add_argument("--command", required=True)
    cmd.add_argument("--install-root", action="append", default=[])

    args = parser.parse_args(argv)
    if args.subcommand == "pid-file-is-own-server":
        return 0 if pid_file_own_server(args.pid_file) else 1
    if args.subcommand == "pid-file-names-listener":
        ok = pid_file_names_listener(args.pid_file, args.pid, args.install_root)
        return 0 if ok else 1
    if args.subcommand == "command-is-install-server":
        return 0 if command_is_install_server(args.command, args.install_root) else 1

    # The pid file is read only when the /health payload turns out incomplete.
    # The listener is resolved with lsof under the same condition; a healthy
    # console pays neither lsof nor ps. On the wire a caller passes a
    # comma- or newline-separated list; --port asks the tool to resolve it.
    if args.listener_pids.strip():
        listener_source = [
            pid.strip()
            for pid in args.listener_pids.replace(",", "\n").splitlines()
            if pid.strip()
        ]
    elif args.port:
        port = args.port
        listener_source = lambda: port_listener_pids(port)
    else:
        listener_source = []
    reason = evaluate(
        health=_load_health(args.health_file),
        workspace=args.workspace,
        runtime=args.runtime,
        pid_file=args.pid_file,
        listener_pids=listener_source,
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
