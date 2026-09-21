"""The gate. Tool calls pass through here before anything executes.

Two rules make this a gate and not a request:

1. **The verdict is computed in the handler**, not asked of the caller. A client
   that omits the check, lies about it, or never read the contract gets the same
   answer.
2. **Approval is server-side state.** A client cannot approve itself by setting
   a flag: it must name an approval issued after trusted human confirmation, and that
   approval is bound to this exact tool and these exact arguments, expires, and
   is single-use.

Authority levels follow `core/docs/authority-model.md`:

    A0  read what is already authorized          -> allowed
    A2  mutate a local artifact                  -> needs a granted approval
    A3  execute under a written mandate          -> needs a live mandate
    A4  irreversible, or never grantable here    -> refused

**External communication.** A tool that sends outside the machine is marked
`external_communication`. The rule from the authority model is that such an act
is never A2-implicit: it needs formal A2, in front of a human, before the send.
That is exactly what a granted approval is: a runtime or trusted-operator record,
bound by hash to this tool and this text, single-use and expiring — so an
external tool is reachable only through the A2 branch below. Declared external
at any other authority is refused outright: there is no human in that path.
"""
from __future__ import annotations

import hashlib
import math
from contextlib import contextmanager
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]
_PATHS_SCRIPTS = _SKILLS / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))

import solar_runtime  # noqa: E402

DELEGATION_CTL = _SKILLS / "solar-router" / "scripts" / "delegation_ctl.py"

A0, A2, A3, A4 = "A0", "A2", "A3", "A4"


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    code: str
    reason: str
    authority: str
    tool: str
    checks: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(allowed=self.allowed, code=self.code, reason=self.reason,
                    authority=self.authority, tool=self.tool, checks=self.checks,
                    gate="solar-mcp/handler")


def gate_root() -> Path:
    return solar_runtime.runtime_dir("mcp")


def approvals_dir() -> Path:
    return gate_root() / "approvals"


def scope_hash(tool: str, arguments: dict) -> str:
    """Binds an approval to one tool and one set of arguments, canonically."""
    payload = json.dumps(dict(tool=tool, arguments=arguments or {},
                              workspace=str(Path(os.environ.get("SOLAR_WORKSPACE") or Path.cwd()).resolve())),
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now() -> float:
    return time.time()


def _read_approval(approval_id: str) -> dict | None:
    if not approval_id or "/" in approval_id or approval_id.startswith("."):
        return None
    path = approvals_dir() / f"{approval_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _consume_approval(approval_id: str, record: dict) -> None:
    record["consumed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = approvals_dir() / f"{approval_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def check_mandate(name: str, action: str, automated: bool = False) -> dict:
    """Ask the universal control point. Its answer, not ours, decides A3."""
    if not name:
        return dict(ok=False, errors=["no mandate named"])
    cmd = [sys.executable, str(DELEGATION_CTL), "check", name, "--action", action]
    if automated:
        cmd.append("--automated")
    # Run it from the workspace it is answering about: the path resolver fails
    # closed when an exported workspace disagrees with the one it discovers from
    # the current directory.
    cwd = os.environ.get("SOLAR_WORKSPACE") or None
    if cwd and not Path(cwd).is_dir():
        cwd = None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(ok=False, errors=[f"delegation_ctl unavailable: {exc}"])
    try:
        return json.loads(proc.stdout or proc.stderr or "{}")
    except ValueError:
        return dict(ok=False, errors=[(proc.stderr or proc.stdout or "no answer").strip()[:300]])


def preflight(tool: str, arguments: dict, registry: dict) -> Verdict:
    """The only way in. Returns a verdict; the handler refuses to act without it."""
    arguments = arguments or {}
    spec = registry.get(tool)
    if spec is None:
        return Verdict(False, "unknown_tool", f"{tool} is not a tool of this server", A4, tool)

    authority = spec["authority"]
    checks: list = [dict(check="authority", value=authority)]

    if spec.get("external_communication"):
        checks.append(dict(check="external_communication", value=True))
        if authority != A2:
            return Verdict(False, "external_communication_refused",
                           "External communication always needs formal A2 in front of a "
                           f"human; {authority} never provides one.", A4, tool, checks)

    if authority == A0:
        return Verdict(True, "read_allowed", "Read-only context needs no approval.",
                       A0, tool, checks)

    if authority == A3:
        mandate = arguments.get("mandate") or spec.get("mandate") or ""
        action = arguments.get("action") or spec.get("action") or ""
        allowed_skills = registry.get("_action_skills", {})
        skill = arguments.get("skill") or ""
        entry = allowed_skills.get(skill)
        checks.append(dict(check="action_skill_registered", value=bool(entry)))
        if not entry:
            return Verdict(False, "skill_not_registered",
                           f"{skill or '(none)'} is not a registered action skill. "
                           "Instruction skills stay native; they never become tools.",
                           A3, tool, checks)
        if action not in entry.get("actions", []):
            checks.append(dict(check="action_allowed", value=False))
            return Verdict(False, "action_not_allowed",
                           f"{action or '(none)'} is not an allowed action of {skill}.",
                           A3, tool, checks)
        checks.append(dict(check="action_allowed", value=True))
        answer = check_mandate(mandate or entry.get("mandate", ""), action,
                               bool(arguments.get("automated")))
        checks.append(dict(check="mandate", value=answer))
        if not answer.get("ok"):
            return Verdict(False, "mandate_denied",
                           "; ".join(answer.get("errors") or ["mandate refused"]),
                           A3, tool, checks)
        return Verdict(True, "mandate_ok",
                       f"Mandate {mandate or entry.get('mandate')} is live for {action}.",
                       A3, tool, checks)

    if authority == A2:
        approval_id = str(arguments.get("approval_id") or "")
        checks.append(dict(check="approval_id_present", value=bool(approval_id)))
        if not approval_id:
            what = ("This verb sends outside the machine"
                    if spec.get("external_communication") else "This verb mutates state")
            return Verdict(False, "approval_required",
                           f"{what}. Use the client confirmation flow; the runtime manages "
                           "the approval internally. If unsupported, a trusted host must supply approval.",
                           A2, tool, checks)
        record = _read_approval(approval_id)
        checks.append(dict(check="approval_found", value=bool(record)))
        if record is None:
            return Verdict(False, "approval_unknown",
                           "No such approval. A client cannot mint one: approvals are "
                           "server-side records granted out of band.", A2, tool, checks)
        if record.get("consumed_at"):
            checks.append(dict(check="approval_unused", value=False))
            return Verdict(False, "approval_consumed",
                           f"That approval was already used at {record['consumed_at']}.",
                           A2, tool, checks)
        try:
            expires = float(record.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires = 0
        if not math.isfinite(expires) or expires <= _now():
            checks.append(dict(check="approval_live", value=False))
            return Verdict(False, "approval_expired", "That approval has expired.",
                           A2, tool, checks)
        # Scope: same tool, same arguments minus the approval id itself.
        scoped = {k: v for k, v in arguments.items() if k != "approval_id"}
        expected = scope_hash(tool, scoped)
        checks.append(dict(check="approval_scope", value=expected == record.get("scope_hash")))
        if expected != record.get("scope_hash"):
            return Verdict(False, "approval_scope_mismatch",
                           "That approval was granted for a different call. Approvals are "
                           "bound to one tool and one set of arguments.", A2, tool, checks)
        return Verdict(True, "approval_ok", "Approval matches this exact call.",
                       A2, tool, checks)

    return Verdict(False, "authority_not_grantable",
                   f"{authority} is never granted by a server handler.", A4, tool, checks)


def consume(tool: str, arguments: dict, registry: dict) -> None:
    """Reserve before execution while holding execution_lock; failures need new consent."""
    spec = registry.get(tool) or {}
    if spec.get("authority") != A2:
        return
    approval_id = str((arguments or {}).get("approval_id") or "")
    record = _read_approval(approval_id)
    if record is not None and not record.get("consumed_at"):
        _consume_approval(approval_id, record)


def record(verdict: Verdict, arguments: dict) -> None:
    """Every decision leaves a trace, allowed or refused."""
    path = gate_root() / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               tool=verdict.tool, allowed=verdict.allowed, code=verdict.code,
               authority=verdict.authority,
               arguments={k: v for k, v in (arguments or {}).items() if k != "approval_id"},
               pid=os.getpid())
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")


@contextmanager
def execution_lock(tool: str, registry: dict):
    """Serialize A2 validation/reservation across stdio server processes."""
    if (registry.get(tool) or {}).get('authority') != A2:
        yield
        return
    import fcntl
    folder = approvals_dir()
    folder.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(folder / '.execution.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield
