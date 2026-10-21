"""One-line, secret-free reason for a restricted reader that exited non-zero.

The router used to report only "restricted provider returned non-zero", which hides the
common causes (no login, no quota, unknown model). The CLI's stderr, and for Antigravity
its private log, is reduced to a short redacted tail. Nothing here changes the outcome:
it only decides what the failure message says, and it never raises.
"""
from __future__ import annotations

import re

MAX_CHARS = 300
MAX_LINES = 3
# Known signatures first: a fixed word is better than any excerpt.
SIGNATURES = (
    (re.compile(r"not logged into|not logged in|please (log ?in|sign in)|login required|unauthenticated", re.I),
     "not_logged_in"),
    (re.compile(r"quota|rate.?limit|usage limit|out of (credits|tokens)|insufficient (credit|balance)", re.I),
     "quota_or_rate_limit"),
    (re.compile(r"(unknown|invalid|unsupported|unavailable|not found).{0,40}model|model.{0,40}(not found|not available|invalid)", re.I),
     "model_unavailable"),
)
_SECRET_NAME = re.compile(r"""(?i)\b([A-Za-z0-9_.-]*(?:key|token|secret|password|credential|authorization)[A-Za-z0-9_.-]*)(["']?)\s*([=:])\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s,}]+)""")
_TOKEN_SHAPES = re.compile(r"(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_.-]+|sk-[A-Za-z0-9_-]{8,}|ya29\.[A-Za-z0-9_.-]+|"
                           r"gh[pous]_[A-Za-z0-9]{20,}|[A-Za-z0-9+/_-]{40,}={0,2})")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def redact(text: str, prompts=()) -> str:
    """Remove prompt copies, bearer/key=value secrets and token-shaped strings."""
    for prompt in prompts:
        if isinstance(prompt, str) and len(prompt) >= 20:
            text = text.replace(prompt, "[PROMPT]")
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SECRET_NAME.sub(lambda m: m.group(1) + m.group(2) + m.group(3) + " [REDACTED]", text)
    return _TOKEN_SHAPES.sub("[REDACTED]", text)


def summarize(returncode, *texts: str, prompts=()) -> str:
    """`exit N: <signature>` when a known cause is recognised, else `exit N: <redacted tail>`."""
    try:
        joined = "\n".join(t for t in texts if isinstance(t, str))
        for pattern, word in SIGNATURES:
            if pattern.search(joined):
                return f"exit {returncode}: {word}"
        lines = [ln.strip() for ln in _CONTROL.sub("", redact(joined, prompts)).splitlines() if ln.strip()]
        tail = " | ".join(lines[-MAX_LINES:])[-MAX_CHARS:]
        return f"exit {returncode}: {tail}" if tail else f"exit {returncode}: no output"
    except Exception:  # noqa: BLE001 - diagnostics must never change the outcome
        return f"exit {returncode}"
