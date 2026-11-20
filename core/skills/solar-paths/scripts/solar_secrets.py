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

import fcntl
import os
import re
import shlex
import sys
import tempfile
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
    try:
        # Exclusive create: a process that lost a race never truncates a store
        # another one already filled.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_HEADER)
    os.chmod(path, 0o600)
    return path


def _parse_text(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
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


def parse_env_file(path) -> dict[str, str]:
    """KEY=VALUE lines into a mapping. A missing file is empty, not an error.

    Deliberately dumb: no interpolation, no command substitution. Used for the
    store and for reading the workspace's visible configuration without handing
    a `.env` to a shell.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_text(raw)


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


_SIMPLE_VALUE = re.compile(r"[A-Za-z0-9_.:/@+=,%-]*")
_PLAIN_DOUBLE = re.compile(r'[^"\\$`]*')


def _secret_line_name(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    return stripped.partition("=")[0].strip().removeprefix("export ").strip()


def _line_complete(line: str) -> bool:
    """False when the line opens a quote it does not close or continues on the next."""
    if line.rstrip("\r\n").endswith("\\"):
        return False
    try:
        shlex.split(line, comments=True, posix=True)
    except ValueError:
        return False
    return True


def _interpret_value(line: str) -> str | None:
    value = _interpret_raw(line)
    if value is not None:
        try:
            value.encode("utf-8")  # strict: the store is read as strict UTF-8
        except UnicodeEncodeError:
            return None
    return value


def _interpret_raw(line: str) -> str | None:
    """The value of one assignment as a shell reads it, or None if ambiguous.

    Only values that can be read without executing anything are interpreted: a
    plain word, a single-quoted string, or a double-quoted string with no
    expansion. A trailing comment, a space, ``$``, a backtick or a backslash
    makes it ambiguous, and an ambiguous line is never moved or deleted.
    """
    value = line.strip()
    if value.startswith("export "):
        value = value[len("export "):].lstrip()
    value = value.partition("=")[2].strip()
    if len(value) >= 2 and value[0] == value[-1] == "'" and "'" not in value[1:-1]:
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"' and _PLAIN_DOUBLE.fullmatch(value[1:-1]):
        return value[1:-1]
    if _SIMPLE_VALUE.fullmatch(value):
        return value
    return None


def _atomic_write(path: Path, text: str, mode: int) -> None:
    """Replace ``path`` through a private temp file in the same directory."""
    path = path.resolve()  # write through a symlink, onto its target
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
            handle.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class MigrationRefused(Exception):
    """The migration cannot run safely; nothing was changed."""


def migrate(workspace: Path) -> dict:
    """Move ``KNOWN_SECRETS`` from the workspace ``.env`` files into the store.

    Never prints or returns a value, only ``path:NAME`` entries. Each name is
    resolved over the store and both ``.env`` files before anything is written:

    * one value, store has none: copied into the store (0600), line removed;
    * one value, store has the same: the stale line is removed;
    * more than one distinct value: conflict, nothing touched for that name;
    * a line that is not plainly readable (trailing comment, expansion):
      ambiguous, nothing touched for that name;
    * an empty assignment carries no value and is removed.

    The store is written, and its new text checked, before any ``.env`` is
    touched. The whole run holds a lock on the store, so two migrations sharing
    one store cannot overwrite each other. A store that is one of the ``.env``
    files refuses to run, before anything is created or its mode changed. A
    ``.env`` with a quote left open or a line continued with ``\\`` cannot be
    split into assignments safely: its secrets are reported as ambiguous and the
    file is not touched. POSIX only (``fcntl``), like the rest of Solar.
    """
    workspace = Path(workspace)
    store = secrets_file().resolve()
    candidates: list[Path] = []
    for candidate in (workspace / ".env", workspace / "sun" / ".env"):
        if not candidate.exists():
            continue
        real = candidate.resolve()
        if real == store:
            raise MigrationRefused(f"the secret store is the same file as {candidate}")
        if real not in candidates:
            candidates.append(real)

    if not _mentions_secret(candidates):
        return dict(moved=[], dropped=[], removed_empty=[], conflicts=[], ambiguous=[])

    store.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(store.parent, 0o700)
    lock_path = store.parent / ".installation.lock"
    with open(lock_path, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            ensure_store()
            return _migrate_locked(store, candidates)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _mentions_secret(candidates: list[Path]) -> bool:
    for path in candidates:
        try:
            raw = path.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        if any(_secret_line_name(line) in KNOWN_SECRETS for line in raw.splitlines()):
            return True
    return False


def _migrate_locked(store: Path, candidates: list[Path]) -> dict:
    stored = read()
    texts: dict[Path, list[str]] = {}
    found: dict[str, list[tuple[Path, int, str | None]]] = {}
    ambiguous_files: list[str] = []
    for path in candidates:
        try:
            raw = path.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        texts[path] = raw.splitlines(keepends=True)
        safe = all(_line_complete(line) for line in texts[path])
        for index, line in enumerate(texts[path]):
            name = _secret_line_name(line)
            if name not in KNOWN_SECRETS:
                continue
            if not safe:
                ambiguous_files.append(f"{path}:{name}")
                continue
            found.setdefault(name, []).append((path, index, _interpret_value(line)))

    result: dict[str, list[str]] = dict(
        moved=[], dropped=[], removed_empty=[], conflicts=[], ambiguous=ambiguous_files)
    to_store: dict[str, str] = {}
    remove: dict[Path, set[int]] = {}
    blocked = {entry.rsplit(":", 1)[1] for entry in ambiguous_files}
    for name, hits in found.items():
        label = [f"{path}:{name}" for path, _, _ in hits]
        if name in blocked or any(value is None for _, _, value in hits):
            result["ambiguous"].extend(label)
            continue
        values = {value for _, _, value in hits if value}
        if stored.get(name):
            values.add(stored[name])
        if len(values) > 1:
            result["conflicts"].extend(label)
            continue
        for (path, index, value), entry in zip(hits, label):
            remove.setdefault(path, set()).add(index)
            if not value:
                result["removed_empty"].append(entry)
            elif stored.get(name):
                result["dropped"].append(entry)
            else:
                result["moved"].append(entry)
        if values and not stored.get(name):
            to_store[name] = next(iter(values))

    if to_store:
        old = store.read_text(encoding="utf-8")
        kept = [line for line in old.splitlines(keepends=True)
                if _secret_line_name(line) not in to_store]
        text = "".join(kept)
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(f"{name}={value}\n" for name, value in to_store.items())
        check = _parse_text(text)
        if any(check.get(name) != value for name, value in to_store.items()):
            raise MigrationRefused("the secret store would not keep the values; nothing changed")
        _atomic_write(store, text, 0o600)

    for path, indexes in remove.items():
        kept = [line for i, line in enumerate(texts[path]) if i not in indexes]
        _atomic_write(path, "".join(kept), path.stat().st_mode & 0o777)
    return result


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
    if command == "migrate":
        if len(argv) < 3:
            sys.stderr.write("usage: solar_secrets.py migrate <workspace>\n")
            return 2
        try:
            result = migrate(Path(argv[2]))
        except MigrationRefused as exc:
            sys.stderr.write(f"migrate refused: {exc}\n")
            return 1
        for label, entries in result.items():
            for entry in entries:
                print(f"{label}: {entry}")
        if not any(result.values()):
            print("nothing to migrate")
        if result["conflicts"]:
            sys.stderr.write(
                "conflict: different values for the same name; "
                "keep the one in use and delete the others by hand.\n")
        if result["ambiguous"]:
            sys.stderr.write(
                "ambiguous: these lines are not plain KEY=VALUE (comment, quotes, "
                "expansion); move them by hand.\n")
        return 1 if result["conflicts"] or result["ambiguous"] else 0
    if command == "names":
        for name in sorted(read()):
            print(name)
        return 0
    sys.stderr.write(
        "usage: solar_secrets.py [path|ensure|migrate <workspace>|status [workspace]|check [workspace]|names]\n"
        "There is no verb that prints a value: this is not a vault UX.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
