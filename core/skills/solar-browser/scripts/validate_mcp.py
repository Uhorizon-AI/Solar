#!/usr/bin/env python3
"""
Read-only: verify that AI client chrome-devtools MCP entries use
`npx chrome-devtools-mcp@latest --browserUrl http://<host>:<port>` aligned with
the Solar browser .env block (defaults 127.0.0.1:9222).

Entrypoint: validate_mcp.sh (same directory).

By default, only validates entries in SOLAR_ROUTER_PROVIDER_PRIORITY that have
a known MCP config path: codex, claude, agy, and agent. The solar-router
provider "agent" is the Cursor CLI; its MCP is read from ~/.cursor/mcp.json.
Provider "agy" (Antigravity) uses multipath MCP configs (local project + globals).

Does not write files. Prints a report; the agent/user applies fixes in the IDE.

Exit 0: all in-scope providers are correctly configured.
Exit 1: at least one in-scope provider has drift or is missing the entry.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

MCP_SERVER_KEY = "chrome-devtools"
ROUTER_MCP_PROVIDERS = frozenset({"codex", "claude", "agy", "agent"})
DEFAULT_PRIORITY_FALLBACK = "codex,claude,agy,agent"


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[4]


def resolve_workspace_root(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return repo_root.expanduser().resolve()
    env_ws = (os.environ.get("SOLAR_WORKSPACE") or "").strip()
    if env_ws:
        return Path(env_ws).expanduser().resolve()
    return repo_root_from_script()


def load_dotenv(env_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def browser_url(env: dict[str, str]) -> str:
    host = (env.get("SOLAR_BROWSER_DEBUG_HOST") or "127.0.0.1").strip()
    port = (env.get("SOLAR_BROWSER_DEBUG_PORT") or "9222").strip()
    return f"http://{host}:{port}"


def expected_npx_command() -> str:
    return "npx"


def expected_npx_args(env: dict[str, str]) -> list[str]:
    return [
        "-y",
        "chrome-devtools-mcp@latest",
        "--browserUrl",
        browser_url(env),
    ]


def parse_router_priority(env: dict[str, str]) -> tuple[str, list[str]]:
    raw = (env.get("SOLAR_ROUTER_PROVIDER_PRIORITY") or env.get("SOLAR_AI_PROVIDER_PRIORITY") or "").strip()
    if not raw:
        raw = DEFAULT_PRIORITY_FALLBACK
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return raw, ordered


def providers_to_validate_mcp(priority_ordered: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in priority_ordered:
        if p in ROUTER_MCP_PROVIDERS and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def json_chrome_entry_ok(entry: object, env: dict[str, str]) -> tuple[bool, str]:
    if not isinstance(entry, dict):
        return False, f"{MCP_SERVER_KEY} is not an object"
    exp_cmd = expected_npx_command()
    exp_args = expected_npx_args(env)
    if entry.get("command") != exp_cmd:
        return False, f'command is {entry.get("command")!r}, expected {exp_cmd!r}'
    if entry.get("args") != exp_args:
        return False, f"args mismatch: got {entry.get('args')!r}, expected {exp_args!r}"
    return True, ""


def load_json_chrome(path: Path) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, "file missing"
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if not isinstance(data, dict):
        return None, "root is not an object"
    mcp = data.get("mcpServers")
    if mcp is None:
        return None, "no mcpServers key"
    if not isinstance(mcp, dict):
        return None, "mcpServers is not an object"
    entry = mcp.get(MCP_SERVER_KEY)
    if entry is None:
        return None, f"no mcpServers.{MCP_SERVER_KEY}"
    if not isinstance(entry, dict):
        return None, f"{MCP_SERVER_KEY} is not an object"
    return entry, None


def file_has_mcp_servers(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and isinstance(data.get("mcpServers"), dict)


def load_codex_chrome(path: Path) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, "file missing"
    raw = path.read_text(encoding="utf-8", errors="replace")
    if tomllib is None:
        return None, "tomllib unavailable (need Python 3.11+)"
    try:
        data = tomllib.loads(raw)
    except Exception as e:
        return None, f"invalid TOML: {e}"
    mcp = data.get("mcp_servers")
    if not isinstance(mcp, dict):
        return None, "no mcp_servers table"
    entry = mcp.get(MCP_SERVER_KEY)
    if entry is None:
        return None, f"no mcp_servers.{MCP_SERVER_KEY}"
    if not isinstance(entry, dict):
        return None, f"{MCP_SERVER_KEY} is not a table"
    return entry, None


def codex_entry_ok(entry: dict, env: dict[str, str]) -> tuple[bool, str]:
    ok, why = json_chrome_entry_ok(entry, env)
    if not ok:
        return ok, why
    if entry.get("enabled") is False:
        return False, "enabled is false"
    return True, ""


def remediation_json_cursor(env: dict[str, str]) -> str:
    return json.dumps(
        {
            MCP_SERVER_KEY: {
                "command": expected_npx_command(),
                "args": expected_npx_args(env),
            }
        },
        indent=2,
        ensure_ascii=False,
    )


def remediation_json_claude_agy(env: dict[str, str]) -> str:
    return json.dumps(
        {
            MCP_SERVER_KEY: {
                "type": "stdio",
                "command": expected_npx_command(),
                "args": expected_npx_args(env),
                "env": {},
            }
        },
        indent=2,
        ensure_ascii=False,
    )


def remediation_codex_toml(env: dict[str, str]) -> str:
    lines = [
        f"[mcp_servers.{MCP_SERVER_KEY}]",
        f'command = "{expected_npx_command()}"',
        "args = [",
    ]
    for a in expected_npx_args(env):
        esc = a.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  "{esc}",')
    lines.extend(["]", "enabled = true"])
    return "\n".join(lines) + "\n"


def agy_candidate_paths(home: Path, workspace: Path) -> list[tuple[str, Path, bool]]:
    """Ordered agy MCP candidates: (label, path, is_local).

    Legacy settings.json is only applicable when it contains mcpServers.
    """
    return [
        ("agy/local", workspace / ".agents" / "mcp_config.json", True),
        ("agy/antigravity-cli", home / ".gemini" / "antigravity-cli" / "mcp_config.json", False),
        ("agy/config", home / ".gemini" / "config" / "mcp_config.json", False),
        ("agy/legacy-settings", home / ".gemini" / "settings.json", False),
    ]


def agy_existing_targets(
    home: Path,
    workspace: Path,
) -> list[tuple[str, Path, str, bool]]:
    """Return existing agy configs: (name, path, kind, effective).

    Local project config is marked effective when present.
    Legacy settings.json included only if it has mcpServers.
    """
    local_exists = (workspace / ".agents" / "mcp_config.json").is_file()
    out: list[tuple[str, Path, str, bool]] = []
    for label, path, is_local in agy_candidate_paths(home, workspace):
        if label == "agy/legacy-settings":
            if not file_has_mcp_servers(path):
                continue
        elif not path.is_file():
            continue
        effective = bool(is_local and local_exists)
        out.append((label, path, "agy", effective))
    return out


def provider_targets(
    home: Path,
    workspace: Path,
    provider: str,
) -> list[tuple[str, Path, str, bool]]:
    """Expand a provider to one or more (name, path, kind, effective) targets."""
    if provider == "codex":
        return [("codex", home / ".codex" / "config.toml", "codex", True)]
    if provider == "claude":
        return [("claude", home / ".claude.json", "claude", True)]
    if provider == "agy":
        return agy_existing_targets(home, workspace)
    if provider == "agent":
        return [("agent", home / ".cursor" / "mcp.json", "cursor", True)]
    raise ValueError(provider)


def run_one(
    name: str,
    path: Path,
    kind: str,
    env: dict[str, str],
    *,
    required: bool,
    effective: bool = False,
) -> bool:
    """Return True if drift or missing/invalid when required."""
    eff = " effective" if effective else ""
    print(f"[{name}]{eff} {path}")
    if name == "agent":
        print(
            '  note: solar-router provider "agent" is the Cursor CLI; '
            "chrome-devtools MCP is configured under Cursor (~/.cursor/mcp.json)."
        )
    if effective:
        print("  note: local project MCP is the effective source for this workspace.")
    bad = False

    def print_codex_suggestion() -> None:
        print("  ---")
        for line in remediation_codex_toml(env).rstrip().split("\n"):
            print(f"    {line}")
        print("  ---")

    def print_json_suggestion() -> None:
        sug = remediation_json_cursor(env) if kind == "cursor" else remediation_json_claude_agy(env)
        print("  ---")
        for line in sug.split("\n"):
            print(f"    {line}")
        print("  ---")

    if kind == "codex":
        entry, err = load_codex_chrome(path)
        if err:
            if required:
                print(f"  status: required — {err}")
                bad = True
                print(f"  suggestion: add or fix [mcp_servers.{MCP_SERVER_KEY}], e.g.:")
                print_codex_suggestion()
            else:
                print(f"  status: skip ({err})")
            print()
            return bad
        ok, why = codex_entry_ok(entry, env)
        if ok:
            print(f"  status: ok (npx + --browserUrl matches {browser_url(env)!r})")
        else:
            print(f"  status: drift — {why}")
            bad = True
            print(f"  suggestion: merge or replace [mcp_servers.{MCP_SERVER_KEY}] with:")
            print_codex_suggestion()
        print()
        return bad

    entry, err = load_json_chrome(path)
    if err:
        if required:
            print(f"  status: required — {err}")
            bad = True
            print(f"  suggestion: add mcpServers.{MCP_SERVER_KEY}, e.g.:")
            print_json_suggestion()
        else:
            print(f"  status: skip ({err})")
        print()
        return bad

    ok, why = json_chrome_entry_ok(entry, env)
    if ok:
        if kind == "cursor":
            print(f"  status: ok (npx + --browserUrl matches {browser_url(env)!r})")
        else:
            print(
                f"  status: ok (npx + --browserUrl matches {browser_url(env)!r}; "
                "other keys e.g. type/env ignored)"
            )
    else:
        print(f"  status: drift — {why}")
        bad = True
        print("  suggestion: set mcpServers to include (merge with your other servers):")
        print_json_suggestion()
    print()
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Validate chrome-devtools MCP entries use npx + "
            "chrome-devtools-mcp@latest --browserUrl (read-only)."
        )
    )
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Solar workspace root for .env + local .agents/mcp_config.json (default: SOLAR_WORKSPACE or inferred)",
    )
    ap.add_argument(
        "--all-clients",
        action="store_true",
        help="Validate codex, cursor, claude, and all existing agy MCP paths; missing = skip",
    )
    ap.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override Path.home() (tests)",
    )
    args = ap.parse_args()

    workspace = resolve_workspace_root(args.repo_root)
    home = (args.home or Path.home()).expanduser().resolve()
    env_path = workspace / ".env"
    env = load_dotenv(env_path)

    raw_priority, priority_ordered = parse_router_priority(env)
    mcp_from_router = providers_to_validate_mcp(priority_ordered)

    print("Solar browser MCP (expected pattern)")
    print(f"  server key: mcpServers.{MCP_SERVER_KEY}")
    print(f"  expected browserUrl: {browser_url(env)} (from workspace .env or defaults)")
    print(f"  workspace: {workspace}")
    print()

    targets: list[tuple[str, Path, str, bool]] = []
    required_map: dict[str, bool] = {}

    if args.all_clients:
        print(
            "Mode: --all-clients (codex, ~/.cursor/mcp.json, claude, all existing agy MCP paths; missing = skip)"
        )
        print(f"  (SOLAR_ROUTER_PROVIDER_PRIORITY {raw_priority!r} — ignored for which paths to check)")
        targets = [
            ("codex", home / ".codex" / "config.toml", "codex", True),
            ("cursor", home / ".cursor" / "mcp.json", "cursor", True),
            ("claude", home / ".claude.json", "claude", True),
        ]
        targets.extend(agy_existing_targets(home, workspace))
        # Also surface candidate locals that are missing under all-clients as skip via run_one
        # when none exist — report primary local candidate as optional skip.
        if not any(t[0].startswith("agy/") for t in targets):
            targets.append(
                ("agy/local", workspace / ".agents" / "mcp_config.json", "agy", False)
            )
        required_map = {t[0]: False for t in targets}
    else:
        print("Solar router (SOLAR_ROUTER_PROVIDER_PRIORITY, else SOLAR_AI_PROVIDER_PRIORITY, else default)")
        print(f"  effective priority: {raw_priority}")
        skipped_router = [p for p in priority_ordered if p not in ROUTER_MCP_PROVIDERS]
        if skipped_router:
            print(f"  not validated (no MCP path here): {', '.join(skipped_router)}")
        print(
            f"  MCP validated for solar-router providers: {', '.join(mcp_from_router) if mcp_from_router else '(none)'}"
        )
        print(
            "  Mapping: agent → ~/.cursor/mcp.json; agy → local .agents/mcp_config.json + "
            "~/.gemini/**/mcp_config.json (+ legacy settings.json if mcpServers). "
            "Use --all-clients to audit all paths."
        )
        print()
        if not mcp_from_router:
            print("No codex, claude, agy, or agent in SOLAR_ROUTER_PROVIDER_PRIORITY — nothing to validate.")
            print()
            return 0
        for p in mcp_from_router:
            expanded = provider_targets(home, workspace, p)
            if p == "agy" and not expanded:
                # Required provider with no configs present: report local candidate as missing.
                expanded = [
                    ("agy/local", workspace / ".agents" / "mcp_config.json", "agy", False)
                ]
            for name, path, kind, effective in expanded:
                targets.append((name, path, kind, effective))
                required_map[name] = True

    print()
    print("Local client configs (read-only)")
    print()

    any_bad = False
    for name, path, kind, effective in targets:
        if run_one(
            name,
            path,
            kind,
            env,
            required=required_map.get(name, True),
            effective=effective,
        ):
            any_bad = True

    print("Notes:")
    if args.all_clients:
        print("  - skip = file or chrome-devtools absent; optional unless you use that IDE.")
        print("  - agy: every existing MCP path is checked (local marked effective when present).")
    else:
        print("  - For providers in SOLAR_ROUTER_PROVIDER_PRIORITY, missing/wrong MCP is reported as required.")
        print('  - "agent" validates ~/.cursor/mcp.json (Cursor CLI in solar-router).')
        print("  - agy: validates all existing candidate paths; local project config is effective when present.")
        print("  - --all-clients: fixed clients + all existing agy paths; ignore priority; missing = skip.")
    print("  - Start Chrome only when needed: run ensure_browser.sh --start right before browser MCP work; MCP must not launch Chrome.")
    print("  - On drift/required, apply the snippet manually; this script does not write ~/.")
    print()

    return 1 if any_bad else 0


if __name__ == "__main__":
    sys.exit(main())
