"""Solar Client-managed native/discovery profile for the shared .agents surface."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from skill_inventory import inventory, settings

REQUIRED = {"solar-mcp", "solar-client", "solar-paths"}


def profile(config: dict) -> tuple[str, set[str]]:
    value = config.get("agents_skill_profile", {})
    if not isinstance(value, dict) or set(value) - {"mode", "essential", "clients"}:
        raise ValueError("Invalid agents_skill_profile")
    mode = value.get("mode", "native")
    essential = value.get("essential", [])
    if mode not in ("native", "discovery") or not isinstance(essential, list) or any(
            not isinstance(v, str) for v in essential):
        raise ValueError("Invalid agents_skill_profile")
    if mode == "discovery" and value.get("clients") != ["codex"]:
        raise ValueError("Discovery is Codex-only; use profile set discovery --codex-only. Antigravity MCP is unsupported")
    return mode, REQUIRED | set(essential)


def verify_mcp(workspace: Path) -> None:
    """Probe the actual configured Codex Solar server before hiding native names."""
    try:
        import tomllib
    except ImportError:
        raise ValueError("Discovery profile needs Python 3.11 or newer") from None
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config = tomllib.loads((home / "config.toml").read_text())
    server = config.get("mcp_servers", {}).get("solar", {})
    if server.get("enabled", True) is not True or not isinstance(server.get("command"), str):
        raise ValueError("Configure the Solar stdio MCP in Codex before enabling discovery")
    env = dict(os.environ)
    supplied = server.get("env", {})
    if not isinstance(supplied, dict) or any(not isinstance(v, str) for v in supplied.values()):
        raise ValueError("Invalid Solar MCP registration environment")
    env.update(supplied)
    bound = env.get("SOLAR_WORKSPACE", "")
    if not bound or Path(bound).resolve() != workspace.resolve():
        raise ValueError("Solar MCP registration is bound to another workspace")
    args = server.get("args", [])
    if not isinstance(args, list) or any(not isinstance(v, str) for v in args):
        raise ValueError("Invalid Solar MCP registration arguments")
    messages = [dict(jsonrpc="2.0", id=1, method="initialize", params=dict(
        protocolVersion="2025-06-18", capabilities={}, clientInfo=dict(name="solar-client", version="1"))),
        dict(jsonrpc="2.0", method="notifications/initialized"),
        dict(jsonrpc="2.0", id=2, method="tools/list")]
    proc = subprocess.run([server["command"], *args],
                          input="".join(json.dumps(m) + "\n" for m in messages),
                          capture_output=True, text=True, timeout=10,
                          env=env, cwd=workspace)
    names = set()
    for line in proc.stdout.splitlines():
        answer = json.loads(line)
        if answer.get("id") == 2:
            names = {t["name"] for t in answer.get("result", {}).get("tools", [])}
    if proc.returncode or not {"solar_capability_search", "solar_capability_describe"} <= names:
        raise ValueError("Registered MCP does not provide discovery; native resources remain available")


def selected(workspace: Path, core: Path, config: dict, *, verify: bool = True) -> dict:
    found = inventory(workspace, core)
    mode, essential = profile(config)
    if mode == "native":
        return found
    if essential - found.keys():
        raise ValueError("Required/essential skills are missing or excluded")
    managed_file = workspace / ".agents/skills/.solar-managed"
    managed = set(managed_file.read_text().splitlines()) if managed_file.is_file() else set()
    for key in essential:
        path = workspace / ".agents/skills" / key
        if (path.exists() or path.is_symlink()) and key not in managed:
            raise ValueError("An unmanaged essential skill conflicts with the discovery bootstrap")
    if verify:
        verify_mcp(workspace)
    return {key: entry for key, entry in found.items() if key in essential}


def preview(workspace: Path, core: Path, config: dict, verify: bool = True) -> dict:
    found = inventory(workspace, core)
    initial = selected(workspace, core, config, verify=verify)
    def size(values):
        return sum(len((key + " " + entry["description"]).encode())
                   for key, entry in values.items())
    return dict(mode=profile(config)[0], surface=".agents (Codex and Antigravity)",
                initial_ids=list(initial), eligible_count=len(found),
                initial_count=len(initial), full_catalog_bytes=size(found),
                initial_catalog_bytes=size(initial),
                measurement="ID + full frontmatter description bytes; not provider tokens")


def write_profile(workspace: Path, core: Path, value: dict) -> None:
    """Use Client's one atomic writer, including identity and portable-key cleanup."""
    if settings(workspace).get("core_source") == "workspace-snapshot":
        raise ValueError("Profile changes currently require a global Client; portable settings remain unchanged")
    library = Path(__file__).with_name("client_lib.sh")
    command = 'source "$1"; solar_client_write_settings_v12 "$2" "$3" preserve_synced=1 "$4"'
    subprocess.run(["bash", "-c", command, "_", str(library), str(workspace),
                    str(core.parent), json.dumps(value)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    configure = sub.add_parser("set")
    configure.add_argument("mode", choices=("native", "discovery"))
    configure.add_argument("--essential", action="append", default=[])
    configure.add_argument("--dry-run", action="store_true")
    configure.add_argument("--codex-only", action="store_true",
                           help="Acknowledge that shared .agents discovery cannot be used by Antigravity")
    index = sub.add_parser("index")
    index.add_argument("--include-antigravity", action="store_true")
    args = parser.parse_args()
    try:
        config = settings(args.workspace)
        if args.command == "set":
            config["agents_skill_profile"] = dict(mode=args.mode, essential=args.essential,
                clients=["codex"] if args.codex_only else [])
        mode, _ = profile(config)
        if mode == "discovery":
            if args.command == "index" and args.include_antigravity:
                raise ValueError("Discovery cannot sync to Antigravity; restore native or use --codex-only")
            print("WARNING: reduced .agents is shared; Antigravity must not use this workspace until native is restored.", file=sys.stderr)
        if args.command == "index":
            for key, entry in selected(args.workspace, args.core, config).items():
                source = str(Path(entry["path"]).parent)
                if any(c in source for c in ("|", "\n", "\r")):
                    raise ValueError("Unsupported inventory path")
                print(f"{key}|{source}")
            return 0
        result = preview(args.workspace, args.core, config)
        if args.command == "set" and not args.dry_run:
            write_profile(args.workspace, args.core, config["agents_skill_profile"])
            result["next_step"] = "Run solar client sync --codex-only to publish; native is the rollback mode."
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Profile refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
