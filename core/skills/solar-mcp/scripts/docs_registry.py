"""`solar_docs`: authorized reading of documentation, contracts and references.

Three kinds of readable unit, all read-only and all bounded:

    <skill id>            an eligible instruction skill or one registered reference
    core-doc:<name>       a Markdown file directly under `core/docs/`
    operation:<name>      the contract of a `solar_execute` operation

Reading never executes anything, grants nothing and never accepts a path.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_registry  # noqa: E402
import operations  # noqa: E402
from mcp_context import OperationError  # noqa: E402
from mcp_gate import A0, A2, A3  # noqa: E402
from skill_inventory import read_unit  # noqa: E402
from solar_paths import resolve_solar_paths  # noqa: E402

CORE_DOC = "core-doc:"
OPERATION = "operation:"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_GOVERNANCE_NOTE = capability_registry._GOVERNANCE_NOTE
_APPROVAL = {
    A0: "None: read-only.",
    A2: "Native client confirmation of this exact operation and arguments, or an existing "
        "single-use approval bound to them. Never granted by an argument.",
    A3: "A live written mandate that allows this action, plus a registered action skill.",
}


def _docs_root() -> Path:
    _workspace, install = resolve_solar_paths()
    return install / "core" / "docs"


def core_docs() -> dict:
    """Authorized documents: regular Markdown files directly under core/docs."""
    root = _docs_root()
    found = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.md")):
        name = path.stem
        if not _NAME.fullmatch(name) or path.is_symlink():
            continue
        try:
            raw = read_unit(path, root)
        except (OSError, ValueError):
            continue
        title = next((line[2:].strip() for line in raw.decode("utf-8", "replace").splitlines()
                      if line.startswith("# ")), name)
        found[CORE_DOC + name] = dict(id=CORE_DOC + name, type="document", namespace="core",
                                      description=title, revision=hashlib.sha256(raw).hexdigest(),
                                      path=path, root=root, raw=raw)
    return found


def search_docs(query: str, limit: int = 10) -> dict:
    terms = set(re.findall(r"\w+", (query or "").casefold()))
    ranked = []
    for key, entry in core_docs().items():
        content = (key + " " + entry["description"]).casefold()
        matched = sorted(t for t in terms if t in content)
        if terms and not matched:
            continue
        ranked.append((-len(matched), key, entry))
    results = [dict(id=key, type="document", description=capability_registry.clip_description(
        entry["description"]), revision=entry["revision"])
        for _, key, entry in sorted(ranked, key=lambda item: item[:2])[:max(1, min(limit, 20))]]
    return dict(results=results, truncated=len(ranked) > len(results))


_CLIENT_CONSENT = ("The client's own tool permission, with no form. A task that is not confined still waits "
                   "for task.authorize_run (native confirmation) before it runs.")


def operation_contract(name: str) -> dict:
    op = operations.OPERATIONS.get(name)
    if op is None:
        raise OperationError("unknown_operation", "Unknown operation. Known: "
                             + ", ".join(operations.OPERATIONS))
    contract = dict(id=OPERATION + name, type="operation", operation=name, summary=op.summary,
                    authority=op.authority, effects=op.effects, approval=_CLIENT_CONSENT if op.client_consent else _APPROVAL[op.authority],
                    arguments=op.schema, errors=list(op.errors) + [
                        "invalid_arguments", "approval_required", "approval_unknown",
                        "approval_expired", "approval_consumed", "approval_scope_mismatch"],
                    call="solar_execute operation=%s arguments={...per the schema above}" % name,
                    governance=_GOVERNANCE_NOTE)
    if op.external_communication:
        contract["external_communication"] = True
    if op.refuses_mandate:
        contract["mandate"] = "Refused: an A3 mandate never activates work."
    return contract


def read(id: str, revision: str = "", reference: str = "", section: str = "", full: bool = False) -> dict:
    if type(full) is not bool:
        raise ValueError("full must be a boolean")
    if section and full:
        raise ValueError("section and full cannot be combined")
    if id.startswith(OPERATION):
        if revision or reference or section or full:
            raise ValueError("operation contracts are returned complete; no revision, reference, section or full")
        return operation_contract(id[len(OPERATION):])
    if id.startswith(CORE_DOC):
        if reference:
            raise ValueError("core documents have no references")
        entry = core_docs().get(id)
        if entry is None:
            raise ValueError("Document is unavailable. Search with scope=docs")
        raw = read_unit(entry["path"], entry["root"])
        current = hashlib.sha256(raw).hexdigest()
        if current != entry["revision"] or revision and revision != current:
            raise ValueError("Document revision changed; search again")
        base = dict(id=id, type="document", revision=current, references=[], namespace="core",
                    governance=_GOVERNANCE_NOTE)
        return capability_registry.render(raw, base, entry["description"], section, full)
    return capability_registry.describe(id, revision, reference, section, full)
