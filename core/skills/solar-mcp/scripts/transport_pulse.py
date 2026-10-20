"""The transport's pulse for long read-only waits.

`task.wait` sleeps between its own reads. While it sleeps, the connection it
came from must not go deaf: a `ping` deserves an answer at once and a
cancellation of the live request deserves an end to the wait. The stdio server
installs, for the request it is handling, one drain function that does exactly
that; the operation calls `wait()` between its slices. Without a drain (a
direct call, a test harness) `wait()` simply sleeps and reports True, so the
operation keeps one behaviour everywhere and the transport keeps its own.
"""
from __future__ import annotations

import threading
import time

_LOCAL = threading.local()


def install(drain) -> None:
    """Set the drain the server answers the transport with for the live request."""
    _LOCAL.drain = drain


def clear() -> None:
    """Forget the drain: the live request is over, however it ended."""
    _LOCAL.drain = None


def wait(seconds: float) -> bool:
    """Sleep up to `seconds`, letting the installed drain answer the transport.

    False means the caller's request was cancelled or the stream closed: stop
    waiting. True means the slice elapsed untouched.
    """
    drain = getattr(_LOCAL, "drain", None)
    if drain is None:
        time.sleep(seconds)
        return True
    return drain(seconds)
