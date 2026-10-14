#!/usr/bin/env python3
"""Client-side registration of planet dashboards (`.solar/settings.json`).

A planet **declares** a surface next to itself, in its own `.solar/dashboards.json`
(what it is and where it answers). This machine **registers** it inside the
`dashboards` block of the workspace settings: which declared surfaces are active
here and, when it needs one, the machine-specific start command (which carries
local paths, so it cannot live in the versioned declaration).

The console joins both and stays read only: it shows the start command as
copyable text and never runs it. This command writes settings only; it never
starts a tool, never probes a port and never touches a planet file. The one
exception is `seed`, which creates or validates a planet's declaration file and
is the only subcommand that writes inside a planet.

Exit codes:
  0  ok
  2  usage error or invalid settings
  5  refusal before any write
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 5

SURFACE_ID = re.compile(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_-]+\Z")
PLANET_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")
NAME_RE = re.compile(r"[A-Za-z0-9_-]+\Z")
MAX_REGISTERED = 120
MAX_COMMAND = 4000
SETTINGS_KEYS = {"enabled", "registered"}
ENTRY_KEYS = {"id", "start_command"}
DECLARATION_RELATIVE = ".solar/dashboards.json"

# Canonical layout/scope written into .solar/settings.json. Kept in sync with
# client_lib.sh and codex_agents.py; this is the single literal for this script.
SOLAR_LAYOUT = "solar-client-v1.2"
SOLAR_SCOPE = "workspace"


class Usage(Exception):
    """Invalid usage or settings (exit 2)."""


class Refusal(Exception):
    """Refusal before any write (exit 5)."""


@dataclass
class Config:
    enabled: bool = True
    registered: list = field(default_factory=list)   # [{"id": str, "start_command": str|null}]
    data: dict = field(default_factory=dict)
    read_path: str = ""


def settings_read_path(workspace: Path) -> Path:
    path = workspace / ".solar/settings.json"
    if not path.is_file():
        legacy = workspace / ".solar/manifest.json"
        if legacy.is_file():
            return legacy
    return path


def load_config(workspace: Path) -> Config:
    path = settings_read_path(workspace)
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Usage(f"invalid Solar workspace settings: {path}: {exc}")
        if not isinstance(data, dict):
            raise Usage(f"Solar workspace settings must be a JSON object: {path}")
    cfg = Config(data=data, read_path=str(path))
    if "dashboards" not in data:
        return cfg
    block = data["dashboards"]
    if not isinstance(block, dict):
        raise Usage("dashboards must be an object")
    unknown = sorted(set(block) - SETTINGS_KEYS)
    if unknown:
        raise Usage(f"unknown key(s) in dashboards: {', '.join(unknown)}")
    if "enabled" in block:
        if not isinstance(block["enabled"], bool):
            raise Usage("dashboards.enabled must be a boolean")
        cfg.enabled = block["enabled"]
    rows = block.get("registered", [])
    if not isinstance(rows, list):
        raise Usage("dashboards.registered must be an array")
    if len(rows) > MAX_REGISTERED:
        raise Usage(f"dashboards.registered holds more than {MAX_REGISTERED} entries")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise Usage("dashboards.registered entries must be objects")
        unknown_entry = sorted(set(row) - ENTRY_KEYS)
        if unknown_entry:
            raise Usage(f"unknown key(s) in a registered entry: {', '.join(unknown_entry)}")
        surface = row.get("id")
        if not isinstance(surface, str) or not SURFACE_ID.fullmatch(surface):
            raise Usage(f"invalid registered dashboard id: {surface!r}")
        if surface in seen:
            raise Usage(f"duplicate registered dashboard id: {surface}")
        seen.add(surface)
        command = row.get("start_command")
        if command is not None:
            if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND:
                raise Usage(f"invalid start command for {surface}")
        cfg.registered.append({"id": surface, "start_command": command})
    return cfg


def write_config(workspace: Path, cfg: Config) -> None:
    """Atomic write of the dashboards block, preserving every other key."""
    write_path = workspace / ".solar/settings.json"
    data = dict(cfg.data)
    data["dashboards"] = {
        "enabled": cfg.enabled,
        "registered": [{"id": row["id"], "start_command": row["start_command"]}
                       for row in sorted(cfg.registered, key=lambda r: r["id"])],
    }
    data["scope"] = SOLAR_SCOPE
    data["layout"] = SOLAR_LAYOUT
    os.makedirs(write_path.parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=write_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, write_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    legacy = write_path.parent / "manifest.json"
    if legacy.is_file() and os.path.realpath(legacy) != os.path.realpath(write_path):
        os.unlink(legacy)


def surface_key(value: str) -> str:
    return value.casefold()


def find(cfg: Config, target: str):
    key = surface_key(target)
    for row in cfg.registered:
        if surface_key(row["id"]) == key:
            return row
    return None


def validate_target(target: str) -> str:
    if not SURFACE_ID.fullmatch(target):
        raise Usage(f"invalid dashboard id: {target!r} (expected <planet>:<name>)")
    return target


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_status(workspace: Path, args) -> int:
    cfg = load_config(workspace)
    info = {"enabled": cfg.enabled,
            "registered": [{"id": r["id"], "start_command": r["start_command"]}
                           for r in sorted(cfg.registered, key=lambda r: r["id"])]}
    if args.json:
        print(json.dumps(info, indent=2, sort_keys=True))
        return EXIT_OK
    print(f"Dashboards: {'enabled' if cfg.enabled else 'disabled'}")
    print(f"registered: {len(cfg.registered)}")
    print("The console joins this registration with each planet's declaration "
          "(planets/<planet>/.solar/dashboards.json).")
    return EXIT_OK


def cmd_list(workspace: Path, args) -> int:
    cfg = load_config(workspace)
    rows = sorted(cfg.registered, key=lambda r: r["id"])
    if args.json:
        print(json.dumps({"enabled": cfg.enabled, "registered": rows}, indent=2, sort_keys=True))
        return EXIT_OK
    if not rows:
        print("(none registered)")
    for row in rows:
        command = row["start_command"] or "(no start command)"
        print(f"{row['id']}\n  start: {command}")
    return EXIT_OK


def cmd_register(workspace: Path, args) -> int:
    cfg = load_config(workspace)
    target = validate_target(args.target)
    command = args.start_command
    if command is not None and (not command.strip() or len(command) > MAX_COMMAND):
        raise Usage("start command must be non-empty and bounded")
    row = find(cfg, target)
    if row is None:
        if len(cfg.registered) >= MAX_REGISTERED:
            raise Usage(f"dashboards.registered holds more than {MAX_REGISTERED} entries")
        cfg.registered.append({"id": target, "start_command": command})
        action = "registered"
    else:
        if command is None:
            print(f"OK: already registered: {row['id']}")
            return EXIT_OK
        row["start_command"] = command
        action = "updated"
    write_config(workspace, cfg)
    print(f"OK: {action} dashboard: {target}")
    print("Settings only: nothing was started and no planet file was read.")
    return EXIT_OK


def cmd_unregister(workspace: Path, args) -> int:
    cfg = load_config(workspace)
    target = validate_target(args.target)
    row = find(cfg, target)
    if row is None:
        print(f"OK: not registered: {target}")
        return EXIT_OK
    cfg.registered.remove(row)
    write_config(workspace, cfg)
    print(f"OK: unregistered dashboard: {row['id']}")
    return EXIT_OK


def cmd_enable(workspace: Path, args) -> int:
    cfg = load_config(workspace)
    if cfg.enabled:
        print("OK: dashboards were already enabled")
        return EXIT_OK
    cfg.enabled = True
    write_config(workspace, cfg)
    print("OK: dashboards enabled. The console will list declared and registered surfaces.")
    return EXIT_OK


def cmd_disable(workspace: Path, args) -> int:
    cfg = load_config(workspace)
    if not cfg.enabled:
        print("OK: dashboards were already disabled")
        return EXIT_OK
    cfg.enabled = False
    write_config(workspace, cfg)
    print("OK: dashboards disabled. Registration is kept; the console shows reports only.")
    return EXIT_OK


TEMPLATE = """{
  "version": 1,
  "dashboards": [
    {
      "name": "example-tool",
      "title": "",
      "description": "",
      "owner": "",
      "updated_at": "",
      "url": "http://127.0.0.1:8777/",
      "mode": "read_only"
    },
    {
      "name": "example-view",
      "title": "",
      "description": "",
      "owner": "",
      "updated_at": "",
      "file": "operations/leadership/reports/daily.html",
      "mode": "read_only"
    }
  ]
}
"""


def _has_uncommitted_changes(root: Path, target: Path) -> bool:
    """True when git tracks the file and reports it modified. Missing git is fine."""
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    if top.returncode != 0:
        return False
    rel = os.path.relpath(target, top.stdout.strip())
    status = subprocess.run(["git", "-C", top.stdout.strip(), "status", "--porcelain", "--", rel],
                            capture_output=True, text=True, timeout=20)
    return status.returncode == 0 and bool(status.stdout.strip())


def cmd_seed(workspace: Path, args) -> int:
    """Create or validate a planet's declaration. The only write inside a planet.

    `--force` never overwrites blind: it writes a timestamped backup next to the
    file first, and refuses outright when the file has uncommitted git changes
    (unless `--allow-dirty`), so a versioned declaration cannot be lost silently.
    """
    planet = args.planet
    if not PLANET_ID.fullmatch(planet) or planet in (".", ".."):
        raise Usage(f"invalid planet name: {planet!r}")
    planets_dir = (workspace / "planets").resolve()
    root = (planets_dir / planet).resolve()
    if not root.is_relative_to(planets_dir):
        raise Usage(f"planet leaves planets/: {planet!r}")
    if not root.is_dir():
        raise Usage(f"no such planet: planets/{planet}")
    solar = root / ".solar"
    if solar.is_symlink():
        raise Refusal(f"planets/{planet}/.solar is a symlink; refusing to write through it")
    target = solar / "dashboards.json"
    if target.is_symlink():
        raise Refusal(f"planets/{planet}/{DECLARATION_RELATIVE} is a symlink; refusing")
    if target.is_file():
        if args.force:
            if _has_uncommitted_changes(root, target) and not args.allow_dirty:
                raise Refusal(f"planets/{planet}/{DECLARATION_RELATIVE} has uncommitted changes; "
                              "commit them or pass --allow-dirty")
            backup = target.with_name(target.name + ".bak")
            backup.write_bytes(target.read_bytes())
            _write_declaration(target, TEMPLATE)
            print(f"OK: backed up to planets/{planet}/.solar/{backup.name} and overwrote "
                  f"planets/{planet}/{DECLARATION_RELATIVE} with the template")
            return EXIT_OK
        try:
            _validate_declaration(target)
        except (OSError, ValueError, TypeError) as exc:
            print(f"ERROR: planets/{planet}/{DECLARATION_RELATIVE} is not valid: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"OK: planets/{planet}/{DECLARATION_RELATIVE} is valid; nothing was changed")
        return EXIT_OK
    os.makedirs(solar, exist_ok=True)
    _write_declaration(target, TEMPLATE)
    print(f"OK: created planets/{planet}/{DECLARATION_RELATIVE}")
    print("Fill in each entry (title, description, owner, updated_at, url, mode), then "
          f"register it: solar client sync dashboards register {planet}:<name>")
    return EXIT_OK


def _write_declaration(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".dashboards.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _validate_declaration(path: Path) -> None:
    """Same shape the console enforces, so `seed` cannot bless an invalid file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("unsupported declaration version")
    rows = data.get("dashboards")
    if not isinstance(rows, list) or len(rows) > 30:
        raise ValueError("dashboards must be a list of at most 30 entries")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every entry must be an object")
        extra = sorted(set(row) - {"name", "title", "description", "owner",
                                   "updated_at", "url", "file", "mode"})
        if extra:
            raise ValueError(f"unknown key(s) in an entry: {', '.join(extra)}")
        missing = [k for k in ("name", "title", "description", "owner", "updated_at",
                               "mode") if k not in row]
        if missing:
            raise ValueError(f"entry is missing: {', '.join(missing)}")
        name = row["name"]
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in seen:
            raise ValueError(f"invalid or duplicate name: {name!r} (a single safe segment, no dots)")
        seen.add(name)
        for key in ("title", "description", "owner", "updated_at"):
            value = row[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError(f"{name}: {key} must be a non-empty bounded string")
        if row["mode"] not in ("read_only", "interactive"):
            raise ValueError(f"{name}: mode must be read_only or interactive")
        url, file = row.get("url"), row.get("file")
        if (url is None) == (file is None):
            raise ValueError(f"{name}: declare exactly one of url or file")
        if url is not None:
            if not isinstance(url, str) or not re.fullmatch(
                    r"http://(?:127\.0\.0\.1|localhost):[1-9][0-9]{0,4}/", url):
                raise ValueError(f"{name}: url must be a loopback HTTP root")
            if not 1 <= int(url.rsplit(":", 1)[1][:-1]) <= 65535:
                raise ValueError(f"{name}: invalid port")
        else:
            if row["mode"] != "read_only":
                raise ValueError(f"{name}: a file view is always read_only")
            if not isinstance(file, str) or not file.strip() or len(file) > 2000:
                raise ValueError(f"{name}: file must be a bounded path")
            parts = Path(file).parts
            if (Path(file).is_absolute() or ".." in parts or not parts
                    or parts[0] != "operations" or Path(file).suffix != ".html"):
                raise ValueError(f"{name}: file must be an HTML page inside operations/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dashboards.py", description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("register")
    p.add_argument("target")
    p.add_argument("--start-command")
    p = sub.add_parser("unregister")
    p.add_argument("target")
    p = sub.add_parser("seed")
    p.add_argument("planet")
    p.add_argument("--force", action="store_true")
    p.add_argument("--allow-dirty", action="store_true",
                   help="overwrite even with uncommitted changes (a backup is still written)")
    sub.add_parser("enable")
    sub.add_parser("disable")
    return parser


COMMANDS = {
    "status": cmd_status, "list": cmd_list,
    "register": cmd_register, "unregister": cmd_unregister,
    "seed": cmd_seed, "enable": cmd_enable, "disable": cmd_disable,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace)
    try:
        return COMMANDS[args.cmd](workspace, args)
    except Usage as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Refusal as exc:
        print(f"ERROR: {exc}. Nothing was changed.", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"ERROR: dashboard registration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
