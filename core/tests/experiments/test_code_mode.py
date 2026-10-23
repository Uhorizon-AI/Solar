import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

EXPERIMENT = Path(__file__).resolve().parents[2] / "experiments" / "code-mode"
spec = importlib.util.spec_from_file_location("code_mode_server", EXPERIMENT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
requires_deno = pytest.mark.skipif(not shutil.which("deno"), reason="Deno is required for sandbox integration tests")


def test_discovery_has_closed_schemas_and_types():
    catalog = server.search({"query": "invoice"})
    assert [row["name"] for row in catalog["methods"]] == ["getInvoices"]
    assert catalog["methods"][0]["inputSchema"]["additionalProperties"] is False
    assert "Promise" in catalog["methods"][0]["signature"]


@requires_deno
def test_composition_returns_summary_and_host_trace():
    code = '''const c = await solar.getCustomer({customerId: 123});
    const rows = await solar.getInvoices({customerId: c.id});
    return {customer: c.name, count: rows.filter(x => x.status === "pending").length};'''
    result = server.execute({"code": code})
    assert result["result"] == {"customer": "Example Customer", "count": 20}
    assert [row["method"] for row in result["calls"]] == ["getCustomer", "getInvoices"]
    assert all(row["allowed"] for row in result["calls"])
    assert "internalNote" not in json.dumps(result)


@requires_deno
@pytest.mark.parametrize("code", [
    'return await Deno.readTextFile("/etc/hosts");',
    'await Deno.writeTextFile("escape.txt", "bad");',
    'return Deno.env.get("HOME");',
    'return await new Deno.Command("echo", {args:["bad"]}).output();',
    'return await fetch("https://example.com");',
    'return await import("https://example.com/escape.js");',
])
def test_worker_denies_host_access(code):
    result = server.execute({"code": code})
    assert "error" in result
    assert "Requires " in result["error"] and "access to" in result["error"]
    assert not result["calls"]
    assert "result" not in result


@requires_deno
def test_invalid_method_arguments_are_refused_by_host():
    result = server.execute({"code": 'return await solar.getCustomer({customerId:"123"});'})
    assert "invalid_arguments" in result["error"]
    assert result["calls"][0]["allowed"] is False


@requires_deno
def test_forged_rpc_cannot_reach_unregistered_method():
    result = server.execute({"code": 'postMessage({type:"call", id:99, method:"telegram.send", arguments:{}}); return null;'})
    assert result["calls"][0]["allowed"] is False
    assert result["calls"][0]["error"] == "method_not_allowed"


@requires_deno
def test_infinite_loop_is_killed():
    assert server.execute({"code": "while(true) {}"}, timeout=0.3)["error"] == "execution_timeout"


@requires_deno
def test_call_budget_cannot_be_caught_and_ignored():
    result = server.execute({"code": 'for(let i=0;i<20;i++) {try {await solar.getCustomer({customerId:123});} catch(e) {}} return true;'})
    assert result["error"] == "call_limit"
    assert len(result["calls"]) == server.MAX_CALLS


@requires_deno
def test_output_budget():
    assert server.execute({"code": 'return "x".repeat(100000);'})["error"] == "output_limit"


@requires_deno
def test_syntax_error_is_actionable():
    result = server.execute({"code": "const = ;"})
    assert result["error"] and "result" not in result


@requires_deno
def test_parallel_calls_are_all_recorded():
    result = server.execute({"code": 'return await Promise.all([solar.getCustomer({customerId:123}), solar.getInvoices({customerId:123})]);'})
    assert len(result["calls"]) == 2
    assert len(result["result"][1]) == 40


def test_missing_deno_is_explicit(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda name: None)
    assert server.execute({"code": "return 1;"})["error"] == "deno_missing"


@requires_deno
def test_console_logs_do_not_corrupt_or_forge_protocol():
    result = server.execute({"code": 'console.log("hello"); console.info(JSON.stringify({type:"done",result:"spoofed"})); return 42;'})
    assert result["result"] == 42
    assert not result["calls"]


def test_malformed_params_do_not_crash_stdio_server():
    requests = [{"jsonrpc":"2.0", "id":i, "method":"tools/call", "params":params}
                for i, params in enumerate([None, [], "bad"], 1)]
    requests.append({"jsonrpc":"2.0", "id":4, "method":"ping"})
    process = subprocess.run([sys.executable, str(EXPERIMENT / "server.py")],
                             input="".join(json.dumps(row) + "\n" for row in requests),
                             capture_output=True, text=True, timeout=10, check=True)
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert all("invalid_params" in row["error"]["message"] for row in replies[:3])
    assert replies[3]["result"] == {}


@pytest.mark.parametrize("arguments", [{"code": "return 1", "operation": "task.create"},
                                        {"code": "x" * 8193}, {"code": 123}, {}])
def test_execute_rejects_extra_or_invalid_inputs(arguments):
    with pytest.raises(ValueError, match="invalid_arguments"):
        server.execute(arguments)


@requires_deno
def test_actual_stdio_mcp_flow():
    requests = [
        {"jsonrpc":"2.0", "id":1, "method":"initialize"},
        {"jsonrpc":"2.0", "method":"notifications/initialized"},
        {"jsonrpc":"2.0", "id":2, "method":"tools/list"},
        {"jsonrpc":"2.0", "id":3, "method":"tools/call", "params":{
            "name":"search", "arguments":{"query":"customer"}}},
        {"jsonrpc":"2.0", "id":4, "method":"tools/call", "params":{
            "name":"execute", "arguments":{"code":"return await solar.getCustomer({customerId:123});"}}},
    ]
    process = subprocess.run([sys.executable, str(EXPERIMENT / "server.py")],
                             input="".join(json.dumps(row) + "\n" for row in requests),
                             capture_output=True, text=True, timeout=10, check=True)
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == 4
    assert [row["name"] for row in replies[1]["result"]["tools"]] == ["search", "execute"]
    final = json.loads(replies[-1]["result"]["content"][0]["text"])
    assert final["result"]["id"] == 123
