import json
import os
import shlex
import subprocess

import pathlib

from client_permissions import (Finding, MCP_READ_TOOLS, MCP_SERVER, MISSING, OK, UNKNOWN,
                                mcp_registered, read_json, unknown)
from .base import BaseProvider, SOLAR_WORKSPACE, env_int


class AgentProvider(BaseProvider):
    name = "agent"
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        # Cursor Agent CLI: -C was removed; use --workspace. --trust avoids
        # interactive workspace prompts in -p/headless mode.
        return (
            f"agent -p -f --approve-mcps --trust --workspace {SOLAR_WORKSPACE}"
        )

    def ask_prefix(self):
        return ["-p", "--trust"]

    def ask_separator(self):
        return ["--"]

    def read_only_args(self, cwd):
        return ["--mode", "ask", "--workspace", str(cwd)], "--mode ask"

    def static_permission_checks(self, home, workspace):
        """Cursor decides by `approvalMode` and the `permissions` lists of its CLI config."""
        user = home / ".cursor" / "cli-config.json"
        files = [user, workspace / ".cursor" / "cli.json"]
        configs = [(path, read_json(path)) for path in files]
        configs = [(path, data) for path, data in configs if data]
        needed = [f"Mcp({MCP_SERVER}:{tool})" for tool in MCP_READ_TOOLS]
        registered = mcp_registered([home / ".cursor" / "mcp.json", workspace / ".cursor" / "mcp.json"])
        if registered is False:
            return [Finding(self.name, "mcp_read", MISSING, "static",
                            f"the {MCP_SERVER} MCP server is not registered for Cursor",
                            setting=f"mcpServers.{MCP_SERVER}", file=str(home / ".cursor" / "mcp.json"),
                            fix="run: solar mcp install --clients cursor")]
        mode = next((d.get("approvalMode") for _, d in reversed(configs) if d.get("approvalMode")), None)
        permissions = [d.get("permissions") or {} for _, d in configs]
        allow = {e for p in permissions for e in p.get("allow", []) if isinstance(e, str)}
        deny = {e for p in permissions for e in p.get("deny", []) if isinstance(e, str)}
        blocked = [e for e in needed if e in deny]
        if blocked:
            return [Finding(self.name, "mcp_read", MISSING, "static", f"denied: {', '.join(blocked)}",
                            setting="permissions.deny", file=str(user),
                            fix=f"remove {', '.join(blocked)} from permissions.deny")]
        if mode != "allowlist":
            return [unknown(self.name, "mcp_read", f"approvalMode={mode or 'unset'} is not modelled; run the probe")]
        absent = [e for e in needed if e not in allow and f"Mcp({MCP_SERVER}:*)" not in allow]
        if absent:
            return [Finding(self.name, "mcp_read", MISSING, "static",
                            f"approvalMode=allowlist and permissions.allow lacks {', '.join(absent)}",
                            setting="permissions.allow", file=str(user),
                            fix=f"add {', '.join(absent)} to permissions.allow")]
        return [Finding(self.name, "mcp_read", OK, "static", "permissions.allow lists the Solar read tools")]

    def stream(self, prompt: str, *, review=None):
        if review is not None:
            yield from self.stream_review(**review)
            return
        """Stream using --output-format stream-json."""
        self.log_prompt(prompt, " --output-format stream-json")
        self.last_usage = None
        new_key = "SOLAR_ROUTER_AGENT_CMD"
        old_key = "SOLAR_AI_AGENT_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        if "--output-format" not in raw:
            raw += " --output-format stream-json"
        parts = shlex.split(raw)
        parts[0] = self.resolve_binary(parts[0])
        cmd = parts + [prompt]

        env = self.prepare_env(os.environ.copy())
        timeout_sec = env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.get_cwd(),
            env=env,
        )

        full_text: list[str] = []
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                full_text.append(text)
                                yield text
                elif event_type == "result":
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        self.last_usage = {
                            "input_tokens": usage.get("inputTokens", 0),
                            "output_tokens": usage.get("outputTokens", 0),
                            "cached_input_tokens": usage.get("cacheReadTokens", 0),
                        }
                    if not full_text:
                        result = event.get("result", "")
                        if result:
                            full_text.append(result)
                            yield result

            proc.wait(timeout=timeout_sec)
            if proc.returncode != 0:
                stderr = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr or "provider returned non-zero")
            if not full_text:
                raise RuntimeError("provider returned empty output")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("provider timed out")
