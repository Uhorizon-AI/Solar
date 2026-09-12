"""Bounded, cancellable subprocesses. Only signal process groups we created."""
from __future__ import annotations
import os
import signal
import subprocess
import time


class ProcessCancelled(Exception):
    pass


def terminate_group(proc, grace=0.5):
    """Terminate descendants even when the group leader has already exited."""
    for sig, delay in ((signal.SIGTERM, grace), (signal.SIGKILL, 0)):
        proc.poll()  # Reap an exited leader before signalling a possibly empty macOS group.
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        if delay:
            time.sleep(delay)
    proc.wait(timeout=5)


def run_managed(argv, *, input=None, timeout=300, cancelled=lambda: False,
                on_start=lambda pid: None, cwd=None, env=None):
    if cancelled():
        raise ProcessCancelled()
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True,
                            cwd=cwd, env=env)
    started = time.monotonic()
    try:
        on_start(proc.pid)
        first = True
        while True:
            if cancelled():
                raise ProcessCancelled()
            if time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                out, err = proc.communicate(input=input if first else None, timeout=0.1)
                if cancelled():
                    raise ProcessCancelled()
                return subprocess.CompletedProcess(argv, proc.returncode, out, err)
            except subprocess.TimeoutExpired:
                first = False
    except BaseException:
        terminate_group(proc)
        raise
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream and not stream.closed:
                stream.close()
