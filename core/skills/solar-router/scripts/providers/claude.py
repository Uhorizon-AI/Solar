import json
import os
import shlex
import subprocess

from cli_permissions import Finding, MCP_READ_TOOLS, MCP_SERVER, MISSING, mcp_registered, read_json, rule_list, solar_read_tools_declare_read_only, unknown
from .base import BaseProvider, SOLAR_WORKSPACE, env_int


class ClaudeProvider(BaseProvider):
    name = "claude"
    default_cmd = "claude -p --permission-mode bypassPermissions --no-session-persistence"
    last_usage: dict | None = None

    def ask_prefix(self):
        return ["-p", "--no-session-persistence"]

    def read_only_args(self, cwd):
        return ["--permission-mode", "plan"], "--permission-mode plan"

    def ask_separator(self):
        return ["--"]

    def static_permission_checks(self, home, workspace):
        """Claude decides by `permissions.allow`/`deny` rules across its settings files."""
        registered = mcp_registered([home / ".claude.json", workspace / ".mcp.json"], project=workspace)
        if registered is False:
            return [Finding(self.name, "mcp_read", MISSING, "static",
                            f"the {MCP_SERVER} MCP server is not registered for Claude",
                            setting=f"mcpServers.{MCP_SERVER}", file=str(home / ".claude.json"),
                            fix="run: solar mcp install --clients claude")]
        files = [home / ".claude" / "settings.json", workspace / ".claude" / "settings.json",
                 workspace / ".claude" / "settings.local.json"]
        found = [(f, (read_json(f) or {}).get("permissions") or {}) for f in files]
        prefix = f"mcp__{MCP_SERVER}"
        tools = [f"{prefix}__{tool}" for tool in MCP_READ_TOOLS]

        def covers(entries, tool):
            return any(isinstance(e, str) and e in (prefix, f"{prefix}__*", tool) for e in entries)

        for source, perms in found:
            denied = [t for t in tools if covers(rule_list(perms, "deny"), t)]
            if denied:
                break
        if denied:
            return [Finding(self.name, "mcp_read", MISSING, "static", f"denied: {', '.join(denied)}",
                            setting="permissions.deny", file=str(source),
                            fix=f"remove the rule matching {', '.join(denied)} from permissions.deny")]
        declared = solar_read_tools_declare_read_only()
        if declared is None:
            return [unknown(self.name, "mcp_read", "could not read the Solar MCP server's tool table; run the probe")]
        if not declared:
            return [Finding(self.name, "mcp_read", MISSING, "static",
                            "Claude's plan mode runs only MCP tools that declare readOnlyHint, and this Solar's read tools do not",
                            setting="annotations.readOnlyHint on solar_search and solar_docs",
                            file="core/skills/solar-mcp/scripts/mcp_server.py",
                            fix="update Solar (the server must declare readOnlyHint); permissions.allow rules do not lift plan mode")]
        return [unknown(self.name, "mcp_read",
                        "the Solar MCP read tools declare readOnlyHint; run the probe to confirm the call reaches the server")]

    def stream(self, prompt: str, *, review=None):
        if review is not None:
            yield from self.stream_review(**review)
            return
        """Stream token-by-token using --include-partial-messages."""
        self.log_prompt(prompt, " --output-format stream-json --include-partial-messages")
        new_key = "SOLAR_ROUTER_CLAUDE_CMD"
        old_key = "SOLAR_AI_CLAUDE_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.default_cmd).strip()
        if "--output-format" not in raw:
            raw += " --output-format stream-json --verbose"
        if "--include-partial-messages" not in raw:
            raw += " --include-partial-messages"
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
                if event_type == "stream_event":
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                full_text.append(text)
                                yield text
                elif event_type == "result":
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        self.last_usage = {
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                            "cached_input_tokens": usage.get("cache_read_input_tokens", 0),
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
