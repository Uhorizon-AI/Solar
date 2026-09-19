#!/usr/bin/env python3
"""Installation secrets: the keys Solar's own transports send with.

One home, outside every tree an IDE indexes:

    <app data>/Solar/secrets/installation.env      (0600, in a 0700 directory)

Override with ``SOLAR_SECRETS_FILE`` — tests point it at a fixture, never at the
live store.

This is **not** a vault and there is no UX for it. Solar is not the Railway of
each planet: a planet keeps its own ``.env`` and boots on its own. What lives
here is the config class the framework itself owns and must never publish: the
credentials with which Solar's runtime authenticates and sends.

    TELEGRAM_BOT_TOKEN          outbound Telegram as the Solar runtime
    SOLAR_N8N_WEBHOOK_SECRET    authenticates the n8n webhook route

Non-secret configuration of this installation (chat id, flags, ports, Chrome)
is a different class and is not stored here.

**Where the guarantee ends.** The file is 0600 and outside the workspace, so it
is not indexed, not in git and not in the context an IDE ships to a model. It is
not a wall against the user's own uid: any process running as Louis can read
it. What this closes is the mediated route — Solar's own skills no longer carry
the token into the harness — not the machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import solar_runtime  # noqa: E402

#: The only names this store is allowed to hold. Anything else belongs to the
#: installation's visible config, to a planet, or to nobody.
KNOWN_SECRETS = ("TELEGRAM_BOT_TOKEN", "SOLAR_N8N_WEBHOOK_SECRET")

_HEADER = """\
# Solar installation secrets — loaded by the process, never by the workspace.
#
# 0600, outside every tree an IDE indexes. Never committed, never synced.
# Only the names in solar_secrets.KNOWN_SECRETS belong here.
"""


def secrets_file() -> Path:
    """Where the installation secrets live."""
    override = os.environ.get("SOLAR_SECRETS_FILE", "").strip()
    if override:
        return solar_runtime.canonical(override)
    return solar_runtime.solar_global_dir() / "secrets" / "installation.env"


def ensure_store() -> Path:
    """Create the empty hole with the right permissions. Never overwrites."""
    path = secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        path.write_text(_HEADER, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def parse_env_file(path) -> dict[str, str]:
    """KEY=VALUE lines into a mapping. A missing file is empty, not an error.

    Deliberately dumb: no interpolation, no command substitution. Used for the
    store and for reading the workspace's visible configuration without handing
    a `.env` to a shell.
    """
    values: dict[str, str] = {}
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def read() -> dict[str, str]:
    """The installation secrets, as stored."""
    return parse_env_file(secrets_file())


def load_into_environ(environ=None, override: bool = True) -> list[str]:
    """Put the stored secrets in the environment. Returns the names loaded.

    Only ``KNOWN_SECRETS`` are loaded. The file is the one place on the machine
    that Solar's runtime reads with its own hands, so a name nobody put there on
    purpose does not get to ride into the environment of the gateway, the
    notifier or the MCP server: `status()` reports it as unknown instead.

    ``override`` is true by default: the store is the authority for these names,
    so a stale copy inherited from a workspace ``.env`` loses to it.
    """
    environ = os.environ if environ is None else environ
    loaded = []
    for key, value in read().items():
        if key not in KNOWN_SECRETS or not value:
            continue
        if key in environ and not override:
            continue
        environ[key] = value
        loaded.append(key)
    return sorted(loaded)


def status() -> dict:
    """What a doctor needs: which names are present, and how exposed the file is."""
    path = secrets_file()
    present = sorted(name for name, value in read().items() if value)
    mode = None
    try:
        mode = oct(path.stat().st_mode & 0o777)
    except OSError:
        pass
    return dict(
        path=str(path),
        exists=path.exists(),
        mode=mode,
        secure=mode in ("0o600", "0o400"),
        present=present,
        missing=[name for name in KNOWN_SECRETS if name not in present],
        unknown=[name for name in present if name not in KNOWN_SECRETS],
    )


def workspace_leaks(workspace: Path) -> list[str]:
    """Files inside the workspace that still carry a name from KNOWN_SECRETS.

    The change closes when this list is empty: these keys must not sit in a file
    the IDE indexes.
    """
    leaks = []
    for candidate in (workspace / ".env", workspace / "sun" / ".env"):
        try:
            raw = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            name = stripped.partition("=")[0].strip().removeprefix("export ").strip()
            if name in KNOWN_SECRETS:
                leaks.append(f"{candidate}:{name}")
    return leaks


def _main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "status"
    if command == "path":
        print(secrets_file())
        return 0
    if command == "ensure":
        print(ensure_store())
        return 0
    if command in ("status", "check"):
        import json

        report = status()
        if len(argv) > 2:
            report["workspace_leaks"] = workspace_leaks(Path(argv[2]))
        print(json.dumps(report, indent=2, sort_keys=True))
        if command == "check":
            ok = report["exists"] and report["secure"] and not report["missing"]
            return 0 if ok else 1
        return 0
    if command == "names":
        for name in sorted(read()):
            print(name)
        return 0
    sys.stderr.write(
        "usage: solar_secrets.py [path|ensure|status [workspace]|check [workspace]|names]\n"
        "There is no verb that prints a value: this is not a vault UX.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
