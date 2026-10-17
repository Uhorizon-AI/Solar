"""Exercise async policy operations with exact-call approvals in isolated tests only."""
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
for _skill in ("solar-mcp", "solar-app", "solar-client", "solar-state", "solar-paths"):
    sys.path.insert(0, str(CORE / "skills" / _skill / "scripts"))
import mcp_approve
import mcp_server


def approved_operation(name, arguments):
    grant = mcp_approve.grant(name, arguments, 900, "isolated rollout regression")
    body, error = mcp_server.call_tool("solar_execute", dict(
        operation=name, arguments=arguments, approval_id=grant["approval_id"]))
    assert not error, body
    return body["result"]


def apply_policy(capacity, enabled=True):
    proposal = approved_operation("async_execution.propose", dict(
        global_capacity=capacity, enabled_reader_profiles=["text_only_review_v1"] if enabled else []))
    return approved_operation("async_execution.apply", dict(
        revision=proposal["revision"], proposal_digest=proposal["proposal_digest"]))
