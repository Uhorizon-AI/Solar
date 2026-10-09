"""Shared identity, filesystem and locking helpers; no CLI imports."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import time

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")

def name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError("invalid identity component")
    return value


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(root, relative):
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ValueError("invalid reference")
    ref = Path(relative.split("#", 1)[0])
    if ref.is_absolute() or ".." in ref.parts:
        raise ValueError("reference must stay inside the planet")
    target = root / ref
    # Refuse symlinks in every component, including ones pointing inward.
    current = root
    for part in ref.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink reference refused")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("reference leaves the planet")
    return target


def planet_root(workspace, planet, agent):
    workspace = Path(workspace).resolve()
    root = within(workspace, f"planets/{name(planet)}")
    contract = within(root, f"agents/{name(agent)}.md")
    if not root.is_dir() or not contract.is_file():
        raise ValueError("planet or canonical agent contract missing")
    return workspace, root, contract


@contextmanager
def locked_parent(path):
    """Serialize destination writers; no unlocked check-then-replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        directory_lock(fd, exclusive=True)
        yield
    finally:
        os.close(fd)


def directory_lock(fd, exclusive):
    limit = time.monotonic() + 5
    while True:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= limit:
                raise TimeoutError("agent memory lock timed out")
            time.sleep(0.05)


