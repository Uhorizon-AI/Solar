"""Standalone synthetic Code Mode experiment; never imports the Solar runtime."""
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 65536
MAX_CALLS = 8
TIMEOUT = 3.0
CATALOG = {
    "getCustomer": {
        "description": "Read one synthetic customer by ID.",
        "signature": "getCustomer(args: {customerId: number}): Promise<{id: number, name: string}>",
        "inputSchema": {"type": "object", "properties": {"customerId": {"type": "integer"}},
                        "required": ["customerId"], "additionalProperties": False},
    },
    "getInvoices": {
        "description": "Read synthetic invoices for a customer; amounts are EUR cents.",
        "signature": "getInvoices(args: {customerId: number}): Promise<Array<{id: string, customerId: number, status: string, amountCents: number, internalNote: string}>>",
        "inputSchema": {"type": "object", "properties": {"customerId": {"type": "integer"}},
                        "required": ["customerId"], "additionalProperties": False},
    },
}
CUSTOMERS = {123: {"id": 123, "name": "Example Customer"}}
INVOICES = [
    {"id": f"INV-{i:03}", "customerId": 123, "status": "pending" if i % 2 else "paid",
     "amountCents": 10000 + i * 100, "internalNote": "Synthetic intermediate field"}
    for i in range(1, 41)
]


def invoke(method, arguments):
    """Host-side closed allowlist, regardless of what the worker emits."""
    if method not in CATALOG:
        raise ValueError("method_not_allowed")
    if (not isinstance(arguments, dict) or set(arguments) != {"customerId"}
            or type(arguments["customerId"]) is not int):
        raise ValueError("invalid_arguments: expected {customerId: integer}")
    customer_id = arguments["customerId"]
    if customer_id not in CUSTOMERS:
        raise ValueError("customer_not_found")
    if method == "getCustomer":
        return dict(CUSTOMERS[customer_id])
    return [dict(row) for row in INVOICES if row["customerId"] == customer_id]


def search(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != {"query"}
            or not isinstance(arguments["query"], str) or len(arguments["query"]) > 200):
        raise ValueError("invalid_arguments: expected {query: string}, max 200 characters")
    terms = arguments["query"].lower().split()
    return {"methods": [{"name": name, **spec} for name, spec in CATALOG.items()
                        if not terms or any(term in (name + json.dumps(spec)).lower() for term in terms)],
            "scope": "synthetic-readonly", "authority": "Discovery grants no execution authority."}


def execute(arguments, timeout=TIMEOUT):
    if (not isinstance(arguments, dict) or set(arguments) != {"code"}
            or not isinstance(arguments["code"], str)
            or len(arguments["code"].encode()) > 8192):
        raise ValueError("invalid_arguments: expected {code: string}, max 8192 bytes")
    trace = []
    result = {"trace_id": uuid.uuid4().hex, "scope": "synthetic-readonly", "calls": trace}
    deno = shutil.which("deno")
    if not deno:
        return {**result, "error": "deno_missing"}
    deadline = time.monotonic() + timeout
    # Empty environment, temporary cwd, no project config or remote dependencies.
    command = [deno, "run", "--no-config", "--no-lock", "--no-prompt", "--no-remote",
               "--no-npm", "--cached-only", "--deny-read", "--deny-write", "--deny-net",
               "--deny-env", "--deny-run", "--deny-ffi", "--deny-sys",
               "--unstable-worker-options", "--v8-flags=--max-old-space-size=64",
               str(ROOT / "runner.js")]
    with tempfile.TemporaryDirectory(prefix="solar-codemode-") as cwd:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, cwd=cwd, start_new_session=True,
                                   env={"PATH": os.defpath, "DENO_NO_UPDATE_CHECK": "1", "NO_COLOR": "1"})
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = b""
        consumed = 0
        try:
            process.stdin.write(json.dumps({"code": arguments["code"], "methods": list(CATALOG)}).encode() + b"\n")
            process.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(max(0, remaining)):
                    return {**result, "error": "execution_timeout"}
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    return {**result, "error": "worker_failed"}
                consumed += len(chunk)
                if consumed > MAX_BYTES:
                    return {**result, "error": "output_limit"}
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("invalid_worker_protocol")
                    kind = event.get("type")
                    if kind == "done":
                        return {**result, "result": event.get("result")}
                    if kind == "failed":
                        return {**result, "error": event.get("error", "execution_failed")}
                    if kind != "call" or type(event.get("id")) is not int:
                        raise ValueError("invalid_worker_protocol")
                    if len(trace) >= MAX_CALLS:
                        return {**result, "error": "call_limit"}
                    entry = {"method": event.get("method"), "arguments": event.get("arguments")}
                    reply = {"type": "reply", "id": event["id"]}
                    try:
                        reply["result"] = invoke(entry["method"], entry["arguments"])
                        entry["allowed"] = True
                    except (ValueError, TypeError) as error:
                        reply["error"] = str(error)
                        entry.update(allowed=False, error=str(error))
                    trace.append(entry)
                    process.stdin.write(json.dumps(reply).encode() + b"\n")
                    process.stdin.flush()
        except (ValueError, BrokenPipeError) as error:
            return {**result, "error": str(error)}
        finally:
            selector.close()
            # Workers are threads of this child, and subprocess creation is denied.
            # Kill the owned process, avoiding a race with an already-exited group.
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            process.wait()
            process.stdin.close()
            process.stdout.close()


TOOLS = [{"name": name, "description": description, "inputSchema": {
    "type": "object", "properties": {field: {"type": "string"}},
    "required": [field], "additionalProperties": False}}
    for name, field, description in [
        ("search", "query", "Discover synthetic read-only methods, schemas and TypeScript signatures."),
        ("execute", "code", "Run a JavaScript async function body using await solar.<method>(args). Explicitly return a compact JSON result. Synthetic data only; no Solar operations or AI clients.")]]


def handle(request):
    method = request.get("method")
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "solar-code-mode-experiment", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("invalid_params: expected object")
        name = params.get("name")
        if name not in ("search", "execute"):
            raise ValueError("unknown_tool")
        value = (search if name == "search" else execute)(params.get("arguments", {}))
        return {"content": [{"type": "text", "text": json.dumps(value)}],
                "isError": "error" in value}
    raise ValueError("method_not_found")


def main():
    while line := sys.stdin.buffer.readline(MAX_BYTES + 1):
        request = None
        try:
            if len(line) > MAX_BYTES:
                raise ValueError("request_limit")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("invalid_request")
            if "id" not in request:
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": handle(request)}
        except (ValueError, TypeError, KeyError) as error:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32602, "message": str(error)}}
        print(json.dumps(response), flush=True)
        if len(line) > MAX_BYTES:
            break


if __name__ == "__main__":
    main()
