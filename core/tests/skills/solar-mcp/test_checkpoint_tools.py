"""Checkpoint persistence goes through exact-call approval, including native confirmation."""
import json
import mcp_approve
import mcp_probe


def body(answer):
    return json.loads(answer["result"]["content"][0]["text"])


def test_checkpoint_gate_exact_call_and_stale_version_over_wire(solar_env):
    args = dict(agent="example:reviewer", responsibility="review", expected_version=0,
                checkpoint=dict(status="waiting", summary="Fixture", next_step="Review"))
    with mcp_probe.Client(env=solar_env.env, cwd=str(solar_env.workspace)) as client:
        denied = client.call_tool("solar_agent_checkpoint_put", args)
        assert body(denied)["refused"]["code"] == "approval_required"
        approval = mcp_approve.grant("solar_agent_checkpoint_put", args, 900, "test")
        approved = dict(args, approval_id=approval["approval_id"])
        saved = client.call_tool("solar_agent_checkpoint_put", approved)
        assert not saved["result"]["isError"], saved
        assert body(saved)["result"]["version"] == 1
        assert client.call_tool("solar_agent_checkpoint_put", approved)["result"]["isError"]
        approval = mcp_approve.grant("solar_agent_checkpoint_put", args, 900, "stale test")
        assert client.call_tool("solar_agent_checkpoint_put", dict(args, approval_id=approval["approval_id"]))["result"]["isError"]
        read = client.call_tool("solar_agent_checkpoint_get", dict(agent=args["agent"], responsibility="review"))
        assert body(read)["result"]["checkpoint"]["version"] == 1
        assert client.call_tool("solar_agent_checkpoint_put", dict(args, expected_version=True))["result"]["isError"]


def test_checkpoint_native_confirmation_handles_nested_schema(solar_env):
    import mcp_server
    args = dict(agent="example:reviewer", responsibility="review", expected_version=0,
                checkpoint=dict(status="active", summary="Fixture", next_step="Review", artifact_refs=["artifact.md"]))
    request = dict(jsonrpc="2.0", id=7, method="tools/call", params=dict(name="solar_agent_checkpoint_put", arguments=args))
    called = []
    def confirm(name, arguments, request_id):
        called.append((name, arguments, request_id))
        return True
    response = mcp_server.handle(request, confirm)
    assert not response["result"]["isError"]
    assert called[0][1]["checkpoint"] == args["checkpoint"]
