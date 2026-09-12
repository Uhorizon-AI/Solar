"""A minimal MCP client, to exercise the server the way a real client would.

It speaks the same stdio JSON-RPC as any other client: it does not import the
handler, it does not share its memory, and it cannot reach the gate except
through the wire.

    python3 mcp_probe.py list
    python3 mcp_probe.py read solar://health
    python3 mcp_probe.py call solar_task_create '{"title":"Prueba"}'
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent / "mcp_server.py"


class Client:
    """Talks to the server over a pipe and nothing else."""

    def __init__(self, env=None, cwd=None):
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, env=env, cwd=cwd)
        self._id = 0
        self.request("initialize", dict(protocolVersion="2025-06-18",
                                        clientInfo=dict(name="mcp_probe", version="0.1.0"),
                                        capabilities={}))
        self.notify("notifications/initialized")

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self.process.stdin.write(json.dumps(
            dict(jsonrpc="2.0", id=self._id, method=method, params=params or {})) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("server closed the pipe: " + (self.process.stderr.read() or "")[:500])
        return json.loads(line)

    def notify(self, method: str, params: dict | None = None) -> None:
        self.process.stdin.write(json.dumps(
            dict(jsonrpc="2.0", method=method, params=params or {})) + "\n")
        self.process.stdin.flush()

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", dict(name=name, arguments=arguments))

    def close(self) -> None:
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        except Exception:
            self.process.kill()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "list"
    with Client() as client:
        if command == "list":
            print(json.dumps(dict(
                resources=client.request("resources/list")["result"]["resources"],
                tools=[t["name"] for t in client.request("tools/list")["result"]["tools"]],
            ), indent=2, sort_keys=True))
        elif command == "read":
            answer = client.request("resources/read", dict(uri=argv[2]))
            print(json.dumps(answer, indent=2, sort_keys=True))
        elif command == "call":
            arguments = json.loads(argv[3]) if len(argv) > 3 else {}
            answer = client.call_tool(argv[2], arguments)
            print(json.dumps(answer, indent=2, sort_keys=True))
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
