"""Opt-in local evidence for restricted Codex reviews.

The provider JSONL and final-message file live in a launch directory that is
deleted when the launch ends, so a failed pilot leaves nothing to attribute.
When SOLAR_ROUTER_REVIEW_EVIDENCE_DIR names an absolute directory, a bounded
copy of those two outputs is kept there. Unset (the default) captures nothing.

Capture is diagnostic only: every failure here is swallowed so it can neither
turn a failed review into a completed one nor the reverse. Only provider
output is written: never argv (it carries the prompt), env, stderr or auth
files, and known secret values are redacted from what is written.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

ENV_DIR = "SOLAR_ROUTER_REVIEW_EVIDENCE_DIR"
ENV_KEEP = "SOLAR_ROUTER_REVIEW_EVIDENCE_KEEP"
DEFAULT_KEEP = 10
MAX_KEEP = 100
MAX_FILE_BYTES = 8 * 1024 * 1024
_RUN = re.compile(r"^\d{8}T\d{6}Z-\d+-[0-9a-f]{8}$")
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH", re.I)
_SECRET_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*|sk-[A-Za-z0-9_-]{16,}")
_REDACTED = "[REDACTED]"


def _keep() -> int:
    raw = (os.getenv(ENV_KEEP) or "").split("#", 1)[0].strip()
    try:
        value = int(raw) if raw else DEFAULT_KEEP
    except ValueError:
        value = DEFAULT_KEEP
    return max(1, min(value, MAX_KEEP))


def _leaves(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value)


def _secrets(env) -> list:
    found = set()
    for key, value in list(env.items()) + list(os.environ.items()):
        if isinstance(value, str) and len(value) >= 8 and _SECRET_NAME.search(key):
            found.add(value)
    home = env.get("CODEX_HOME")
    if home:
        try:
            raw = (Path(home) / "auth.json").read_text(encoding="utf-8")
            found.add(raw.strip())
            found.update(v for v in _leaves(json.loads(raw)) if len(v) >= 8)
        except (OSError, ValueError):
            pass
    return sorted(found, key=len, reverse=True)


def _clean(data, secrets):
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    for secret in secrets:
        data = data.replace(secret, _REDACTED)
    data = _SECRET_SHAPE.sub(_REDACTED, data)
    raw = data.encode("utf-8")
    truncated = len(raw) > MAX_FILE_BYTES
    if truncated:
        raw = raw[:MAX_FILE_BYTES]
    return raw, truncated


def _root(configured: str) -> Path:
    root = Path(configured)
    if not root.is_absolute():
        raise ValueError("evidence directory must be absolute")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if root.is_symlink() or info.st_uid != os.getuid():
        raise ValueError("evidence directory must be a real directory owned by the current user")
    os.chmod(root, 0o700)
    return root


def _write(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(raw)


def _prune(root: Path, keep: int) -> None:
    runs = sorted(p for p in root.iterdir() if _RUN.match(p.name) and p.is_dir() and not p.is_symlink())
    for old in runs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def capture_codex(argv, env, stdout, returncode, timed_out=False) -> None:
    """Keep redacted JSONL stdout and the final-message file; never raises."""
    configured = (os.getenv(ENV_DIR) or "").strip()
    if not configured:
        return
    try:
        root = _root(configured)
        secrets = _secrets(env or {})
        name = "%s-%d-%s" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid(), os.urandom(4).hex())
        run = root / name
        run.mkdir(mode=0o700)
        events, events_cut = _clean(stdout or "", secrets)
        _write(run / "events.jsonl", events)
        message_cut = None
        try:
            path = argv[argv.index("--output-last-message") + 1]
            message, message_cut = _clean(Path(path).read_bytes(), secrets)
            _write(run / "last-message.json", message)
        except (OSError, ValueError, IndexError):
            pass  # absent or unreadable final message is itself evidence
        meta = dict(provider="codex", returncode=returncode, timed_out=bool(timed_out),
                    events_truncated=events_cut, last_message_truncated=message_cut,
                    last_message_present=message_cut is not None)
        _write(run / "meta.json", json.dumps(meta, sort_keys=True).encode("utf-8"))
        _prune(root, _keep())
    except Exception as exc:  # noqa: BLE001 - evidence must never alter the review outcome
        print("[solar-router] review evidence not captured: " + type(exc).__name__, file=sys.stderr)
