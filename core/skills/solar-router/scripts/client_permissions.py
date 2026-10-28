"""Does each client's own permission layer allow what Solar needs and forbid what it forbids?

Capability is not permission: a flag Solar passes is a request, and the client's
settings decide what runs. Two checks per client:

- `mcp_read`: the client, launched as `ask` launches it, may call the read tools of
  the Solar MCP server.
- `write_guard`: that same launch cannot write to disk.

Two tiers share one result shape. The static tier reads the client's settings
(cheap, no model call, shown by `solar status`). The probe launches the client
through `BaseProvider.ask`, the same construction a router question uses, so there
is no second flag set; it costs tokens and runs only when asked. The probe judges
by evidence outside the model's text: the Solar MCP server's own audit log for the
read call, and the file system for the write canary.

Solar reads settings and proposes the exact change. It never writes to a client's
configuration.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

OK, MISSING, TOO_PERMISSIVE, UNKNOWN = "ok", "missing", "too_permissive", "unknown"
STATUSES = (OK, MISSING, TOO_PERMISSIVE, UNKNOWN)
CHECKS = ("mcp_read", "write_guard")
CLIENTS = ("claude", "codex", "agent", "agy")
MCP_SERVER = "solar"
MCP_READ_TOOLS = ("solar_search", "solar_docs")
STORE_NAME = "client-permissions.json"
PROBE_TIMEOUT_SEC = 180


@dataclass(frozen=True)
class Finding:
    client: str
    check: str
    status: str
    tier: str = "static"  # static | probe
    detail: str = ""
    setting: str = ""  # the exact setting to change, empty when nothing is to change
    file: str = ""
    fix: str = ""

    def __post_init__(self):
        if self.status not in STATUSES or self.check not in CHECKS:
            raise ValueError(f"invalid finding {self.check}={self.status}")


def unknown(client, check, detail, *, tier="static", fix=""):
    """What is not verified is never `ok`."""
    return Finding(client, check, UNKNOWN, tier, detail, fix=fix)


def read_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_toml(path: Path):
    try:
        import tomllib
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (ImportError, OSError, ValueError):
        return None


def mcp_registered(candidates, key="mcpServers", server=MCP_SERVER):
    """Whether any JSON file registers the Solar server; `None` when none is readable."""
    readable = False
    for path in candidates:
        data = read_json(path)
        if data is None:
            continue
        readable = True
        servers = data.get(key)
        if isinstance(servers, dict) and server in servers:
            return True
    return False if readable else None


# --- static tier ------------------------------------------------------------

def static_checks(provider, home: Path, workspace: Path) -> list[Finding]:
    """The provider's own reading of its settings; one finding per check."""
    findings = provider.static_permission_checks(home, workspace)
    seen = {f.check for f in findings}
    return findings + [unknown(provider.name, c, "no readable settings model for this client")
                       for c in CHECKS if c not in seen]


def installed(provider) -> bool:
    try:
        provider.resolve_binary((provider.build_default_cmd() or provider.name).split()[0])
    except RuntimeError:
        return False
    return True


def available_providers(only=None):
    from providers import PROVIDERS
    names = [n for n in CLIENTS if not only or n in only]
    return [PROVIDERS[n] for n in names if n in PROVIDERS and installed(PROVIDERS[n])]


def run_static(only=None, home=None, workspace=None) -> list[Finding]:
    from providers.base import SOLAR_WORKSPACE
    home = Path(home) if home else Path.home()
    workspace = Path(workspace) if workspace else SOLAR_WORKSPACE
    out = []
    for provider in available_providers(only):
        out += static_checks(provider, home, workspace)
    return out


# --- stored probe result ----------------------------------------------------

def store_path() -> Path:
    from providers.base import _runtime_router_dir
    return _runtime_router_dir() / STORE_NAME


def load_probe():
    data = read_json(store_path())
    if not data or not isinstance(data.get("results"), list):
        return None
    return data


def save_probe(findings: list[Finding]) -> None:
    """Router machine state: the answer depends on this machine's client settings."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(probed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   results=[asdict(f) for f in findings])
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def age_label(stamp: str, now=None) -> str:
    try:
        then = time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (TypeError, ValueError):
        return "unknown age"
    seconds = max(0, int((now or time.time()) - then))
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "just now"


# --- live probe -------------------------------------------------------------

def audit_has_call(marker: str) -> bool:
    """Did the Solar MCP server itself receive a call carrying `marker`?

    The server writes every decision to its audit log, with the arguments. That
    evidence is independent of what the client says happened, and it makes no
    assumption about why a client that did not reach the server did not.
    """
    mcp_scripts = Path(__file__).resolve().parents[2] / "solar-mcp" / "scripts"
    if str(mcp_scripts) not in sys.path:
        sys.path.insert(0, str(mcp_scripts))
    import mcp_gate
    try:
        with (mcp_gate.gate_root() / "audit.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                if marker in line:
                    row = json.loads(line)
                    return row.get("kind") == "decision" and bool(row.get("allowed"))
    except (OSError, ValueError):
        pass
    return False


def probe_mcp_read(provider, workspace: Path) -> Finding:
    marker = f"solar-permission-probe-{uuid.uuid4().hex[:12]}"
    prompt = (f"Call the tool solar_search exactly once with arguments "
              f'{{"scope":"operations","query":"{marker}"}}. Call no other tool. '
              "Then reply with the single word DONE, or say in one sentence what stopped you.")
    try:
        answer = provider.ask(prompt, cwd=workspace)
    except (RuntimeError, TimeoutError) as exc:
        return unknown(provider.name, "mcp_read", f"the client did not answer: {str(exc)[:200]}", tier="probe")
    if audit_has_call(marker):
        return Finding(provider.name, "mcp_read", OK, "probe", "the Solar MCP server received the read call")
    reply = " ".join(answer.text.split())[:200]
    return Finding(provider.name, "mcp_read", MISSING, "probe",
                   f"the Solar MCP server received no call; the client said: {reply}",
                   **fix_for(provider, "mcp_read"))


def probe_write_guard(provider) -> Finding:
    scratch = Path(tempfile.mkdtemp(prefix="solar-permission-probe-"))
    marker = f"canary-{uuid.uuid4().hex[:12]}.txt"
    prompt = (f"Create a file named {marker} in the current folder containing the word canary. "
              "Use whatever tool you have, and touch nothing else. "
              "Then reply DONE, or say in one sentence what stopped you.")
    try:
        try:
            provider.ask(prompt, cwd=scratch)
            failure = None
        except (RuntimeError, TimeoutError) as exc:
            failure = str(exc)[:200]
        if (scratch / marker).exists():
            return Finding(provider.name, "write_guard", TOO_PERMISSIVE, "probe",
                           "the client created the file although it was asked for read-only mode",
                           **fix_for(provider, "write_guard"))
        if failure:
            return unknown(provider.name, "write_guard", f"the client did not answer: {failure}", tier="probe")
        return Finding(provider.name, "write_guard", OK, "probe", "the client did not create the canary file")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def fix_for(provider, check: str) -> dict:
    """The change that static knowledge of this client would propose, for a probe verdict."""
    for finding in provider.static_permission_checks(Path.home(), probe_workspace()):
        if finding.check == check and finding.fix:
            return dict(setting=finding.setting, file=finding.file, fix=finding.fix)
    return dict(fix=provider.permission_fix_hint(check))


def probe_workspace() -> Path:
    from providers.base import SOLAR_WORKSPACE
    return SOLAR_WORKSPACE


def run_probe(only=None, checks=CHECKS, workspace=None) -> list[Finding]:
    workspace = Path(workspace) if workspace else probe_workspace()
    out = []
    for provider in available_providers(only):
        if "mcp_read" in checks:
            out.append(probe_mcp_read(provider, workspace))
        if "write_guard" in checks:
            out.append(probe_write_guard(provider))
    return out


# --- rendering --------------------------------------------------------------

def combine(static: Finding, probe) -> str:
    """Either tier reporting a problem stands; otherwise any `ok`; otherwise `unknown`."""
    statuses = [static.status] + ([probe.status] if probe else [])
    for bad in (MISSING, TOO_PERMISSIVE):
        if bad in statuses:
            return bad
    return OK if OK in statuses else UNKNOWN


def summary(static: list[Finding]):
    """One state and one line for `solar status`: WARN when something is wrong, never a model call."""
    stored = load_probe()
    probes = {}
    for row in (stored or {}).get("results", []):
        try:
            probes[(row["client"], row["check"])] = Finding(**row)
        except (KeyError, TypeError, ValueError):
            continue
    if not static:
        return "INFO", "no installed client"
    bad, unverified = [], 0
    for finding in static:
        status = combine(finding, probes.get((finding.client, finding.check)))
        if status in (MISSING, TOO_PERMISSIVE):
            bad.append(f"{finding.client} {finding.check} {status}")
        elif status == UNKNOWN:
            unverified += 1
    probed = f"probe {age_label(stored['probed_at'])}" if stored else "probe never run"
    if bad:
        return "WARN", f"{'; '.join(bad)} ({probed})"
    if unverified:
        return "INFO", f"{unverified} check(s) unverified ({probed})"
    return "OK", f"all checks ok ({probed})"


def render(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        lines.append(f"{f.client:7} {f.check:12} {f.status:14} [{f.tier}] {f.detail}")
        if f.status in (MISSING, TOO_PERMISSIVE) and (f.fix or f.setting):
            where = f" in {f.file}" if f.file else ""
            lines.append(f"        fix: {f.fix or f.setting}{where}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("static", "probe", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--client", action="append", choices=CLIENTS)
        p.add_argument("--json", action="store_true")
        if name == "probe":
            p.add_argument("--check", action="append", choices=CHECKS)
    args = parser.parse_args(argv)
    only = set(args.client or [])
    if args.command == "probe":
        findings = run_probe(only, tuple(args.check or CHECKS))
        save_probe(findings)
    else:
        findings = run_static(only)
    if args.command == "summary":
        state, detail = summary(findings)
        print(json.dumps(dict(state=state, detail=detail)) if args.json else f"{state}\t{detail}")
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print(render(findings) or "no installed client")
    return 1 if any(f.status in (MISSING, TOO_PERMISSIVE) for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
