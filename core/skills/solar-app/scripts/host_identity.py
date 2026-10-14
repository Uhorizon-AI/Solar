#!/usr/bin/env python3
"""Console identity policy: the single decision point.

A console answering on the loopback port is reusable only when it serves the
workspace AND the runtime this caller expects. Every path that decides whether
to reuse, adopt, stop or report a console goes through ``assess`` (directly or
through the ``assess`` CLI below): ``check_host.sh`` (with and without flag),
``ensure_host.sh``, ``start_host.sh`` and ``stop_host.sh``.

Identity is two physical paths, never strings: ``workspace`` (the workspace the
console serves) and ``runtime`` (the framework runtime root of the process).
Both sides are compared after ``realpath`` so a symlinked path and its target
are one identity. Nothing else is exposed: no secrets, tokens or file contents.

States returned by ``assess``:

- ``match``        workspace and runtime both reported and both equal.
- ``mismatch``     a reported value differs. Never reusable, never stopped here.
- ``legacy``       a console that reports neither value (older release).
- ``partial``      exactly one value reported, and it is equal.
- ``unreachable``  nothing answers on loopback (or the answer timed out).
- ``invalid``      something answers but it is not a Solar console.

``legacy`` and ``partial`` need an independent proof of ownership before they
are adopted (see ``host_lib.sh``); ``match`` is its own proof.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PATHS_SCRIPTS = _SCRIPT_DIR.parent.parent / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))

import solar_runtime  # noqa: E402

SERVICE = "solar-console"
PRODUCTION_PORT = 9000
TEST_MODE_ENV = "SOLAR_APP_TEST_MODE"
TEST_PORT_ENV = "SOLAR_APP_TEST_PORT"
IDENTITY_KEYS = ("workspace", "runtime")
ACCEPTED = "match"
NEEDS_PROOF = ("legacy", "partial")


def canonical(path: str | os.PathLike[str]) -> str:
    """Physical path: expanduser + realpath."""
    return str(solar_runtime.canonical(path))


def resolve_port(env: dict[str, str] | None = None) -> int:
    """The console port. Fixed at 9000 except for tests.

    The override needs BOTH ``SOLAR_APP_TEST_MODE=1`` and ``SOLAR_APP_TEST_PORT``
    in the process environment, and it can never select 9000 itself. Workspace
    ``.env`` files cannot set either variable (see ``host_lib.sh`` and
    ``host_workspace_context.py``), so no deployment configuration moves the
    production port.
    """
    env = os.environ if env is None else env
    if env.get(TEST_MODE_ENV, "").strip() == "1":
        raw = env.get(TEST_PORT_ENV, "").strip()
        if raw.isdigit() and 1024 <= int(raw) <= 65535 and int(raw) != PRODUCTION_PORT:
            return int(raw)
    return PRODUCTION_PORT


def local_identity(workspace: str | os.PathLike[str]) -> dict[str, str]:
    """Identity of this process: the workspace it serves and its runtime root."""
    return {"workspace": canonical(workspace), "runtime": str(solar_runtime.runtime_root())}


def compare(payload: object, expected: dict[str, str]) -> tuple[str, list[str]]:
    """Classify a /health payload against the expected identity.

    Returns (state, differing keys). Pure: the only place the rule lives.
    """
    reported: dict[str, str] = {}
    if isinstance(payload, dict):
        for key in IDENTITY_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                reported[key] = canonical(value)
    differing = [key for key, value in reported.items() if value != expected[key]]
    if differing:
        return "mismatch", differing
    if len(reported) == len(IDENTITY_KEYS):
        return "match", []
    if not reported:
        return "legacy", []
    return "partial", []


def fetch_health(base_url: str, timeout: float = 3.0):
    """GET /health on loopback. A configured proxy is never used."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base_url.rstrip("/") + "/health", timeout=timeout) as response:
        return response.status, json.load(response)


def assess(base_url: str, expected: dict[str, str], timeout: float = 3.0) -> dict:
    """Probe the console and decide. Returns state, reason, observed identity."""
    result = {"state": "unreachable", "reason": "", "expected": expected, "observed": {}}
    try:
        status, payload = fetch_health(base_url, timeout)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        result["reason"] = "console unreachable: " + type(exc).__name__
        return result
    if status != 200 or not isinstance(payload, dict) or payload.get("service") != SERVICE \
            or not payload.get("process_ok"):
        result["state"] = "invalid"
        result["reason"] = "the listener is not a Solar console"
        return result
    result["observed"] = {key: payload[key] for key in IDENTITY_KEYS
                          if isinstance(payload.get(key), str) and payload[key].strip()}
    state, differing = compare(payload, expected)
    result["state"] = state
    result["reason"] = {
        "match": "console identity verified (workspace and runtime)",
        "mismatch": "console identity mismatch: " + " and ".join(differing) + " differ",
        "legacy": "console identity unverified: the console reports neither workspace nor runtime",
        "partial": "console identity unverified: the console reports only part of its identity "
                   "(workspace and runtime are both required)",
    }[state]
    return result


def loopback_listener_pids(port: int) -> list[str]:
    """PIDs listening on a loopback address of the port. Empty without lsof.

    A listener bound to another address (a LAN address or the wildcard) is not
    this console: Solar listens on loopback only.
    """
    try:
        listed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids: list[str] = []
    current = ""
    for line in listed.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            current = line[1:]
        elif line.startswith("n") and current:
            host = line[1:].rsplit(":", 1)[0].strip("[]")
            try:
                loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
            if loopback and current not in pids:
                pids.append(current)
    return pids


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: host_identity.py port | assess --base-url URL [--workspace PATH] | listeners PORT",
              file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "port":
        print(resolve_port())
        return 0
    if cmd == "listeners":
        print("\n".join(loopback_listener_pids(int(rest[0]))))
        return 0
    if cmd == "assess":
        args = dict(zip(rest[::2], rest[1::2]))
        workspace = args.get("--workspace") or os.environ.get("SOLAR_WORKSPACE", "")
        if not workspace:
            print("error\tSOLAR_WORKSPACE is not set")
            return 2
        result = assess(args["--base-url"], local_identity(workspace))
        observed = result["observed"]
        print("\t".join([result["state"], result["reason"],
                         observed.get("workspace", ""), observed.get("runtime", "")]))
        return 0 if result["state"] == ACCEPTED else 1
    print("unknown command: " + cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
