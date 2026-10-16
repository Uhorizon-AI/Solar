"""Test helper: the pid of a process that really ran, ended and was reaped."""
from __future__ import annotations

import subprocess
import sys


def dead_pid() -> int:
    """A pid nobody runs. It belonged to a child that exited and was waited for, so it is in
    range on every platform (unlike an invented number), and `ps` answers that it is gone."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid
