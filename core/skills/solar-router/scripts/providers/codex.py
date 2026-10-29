import importlib.util
import json
import os
import pathlib
import shlex
import subprocess
import sys

from cli_permissions import (Finding, MCP_SERVER, MISSING, OK, TOO_PERMISSIVE,
                             read_toml, unknown)
from .base import BaseProvider, SOLAR_WORKSPACE, env_int


class CodexProvider(BaseProvider):
    name = "codex"
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        # Codex dropped --full-auto; current CLIs take --sandbox instead.
        # Exotic installs can override the whole command with SOLAR_ROUTER_CODEX_CMD.
        return (
            "codex exec --skip-git-repo-check --sandbox workspace-write "
            f"-C {SOLAR_WORKSPACE} --"
        )

    def ask_prefix(self):
        return ["exec", "--skip-git-repo-check"]

    def read_only_args(self, cwd):
        return ["--sandbox", "read-only", "-C", str(cwd)], "--sandbox read-only"

    def ask_separator(self):
        return ["--"]

    def static_permission_checks(self, home, workspace):
        """Codex decides by `approval_policy`, `approvals_reviewer` and `mcp_servers` in config.toml.

        `--sandbox read-only` on the command line overrides `sandbox_mode`, but not the
        approval path: an automatic reviewer can approve leaving that sandbox.
        """
        codex_home = pathlib.Path(os.getenv("CODEX_HOME") or home / ".codex")
        path = codex_home / "config.toml"
        config = read_toml(path)
        if config is None:
            why = ("needs Python 3.11+ (tomllib) to read it" if importlib.util.find_spec("tomllib") is None
                   else "is missing or unreadable")
            return [unknown(self.name, c, f"{path} {why}") for c in ("mcp_read", "write_guard")]
        projects = config.get("projects")
        project = projects.get(str(workspace)) if isinstance(projects, dict) else None
        project = project if isinstance(project, dict) else {}
        policy = project.get("approval_policy", config.get("approval_policy"))
        reviewer = project.get("approvals_reviewer", config.get("approvals_reviewer"))
        servers = config.get("mcp_servers")
        servers = servers if isinstance(servers, dict) else {}
        if MCP_SERVER not in servers:
            read = Finding(self.name, "mcp_read", MISSING, "static", f"the {MCP_SERVER} MCP server is not registered for Codex",
                           setting=f"mcp_servers.{MCP_SERVER}", file=str(path), fix="run: solar mcp install --clients codex")
        elif isinstance(servers[MCP_SERVER], dict) and servers[MCP_SERVER].get("enabled") is False:
            read = Finding(self.name, "mcp_read", MISSING, "static", f"mcp_servers.{MCP_SERVER} is disabled",
                           setting=f"mcp_servers.{MCP_SERVER}.enabled", file=str(path), fix="set enabled = true")
        else:
            read = unknown(self.name, "mcp_read", "registered; only the probe shows whether a read call is approved")
        if policy == "never":
            write = Finding(self.name, "write_guard", OK, "static", 'approval_policy = "never": no path out of the read-only sandbox')
        elif reviewer and reviewer != "user" and policy:
            where = f'projects."{workspace}"' if "approval_policy" in project else "top level"
            write = Finding(self.name, "write_guard", TOO_PERMISSIVE, "static",
                            f'approval_policy = "{policy}" with approvals_reviewer = "{reviewer}" ({where}) can approve leaving --sandbox read-only',
                            setting="approval_policy", file=str(path),
                            fix='set approval_policy = "never" (or remove approvals_reviewer, or set it to "user") for the Solar workspace',
                            snippet=f'[projects."{workspace}"]\napproval_policy = "never"')
        else:
            write = unknown(self.name, "write_guard", f"approval_policy={policy or 'unset'}; only the probe shows whether read-only holds")
        return [read, write]

    def stream(self, prompt: str, *, review=None):
        if review is not None:
            yield from self.stream_review(**review)
            return
        self.log_prompt(prompt, " --json")
        self.last_usage = None
        new_key = "SOLAR_ROUTER_CODEX_CMD"
        old_key = "SOLAR_AI_CODEX_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        parts = shlex.split(raw)
        parts[0] = self.resolve_binary(parts[0])

        # Insert --json before -- separator if present, otherwise append it
        if "--" in parts:
            sep_idx = parts.index("--")
            parts.insert(sep_idx, "--json")
        else:
            parts.append("--json")

        cmd = parts + [prompt]
        env = self.prepare_env(os.environ.copy())
        timeout_sec = env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300)
        debug = os.getenv("SOLAR_ROUTER_CODEX_DEBUG_EVENTS", "").strip() == "1"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.get_cwd(),
            env=env,
        )

        deltas: list[str] = []
        last_item_message: str | None = None
        fallback_result: str | None = None
        logged_unknown: set[str] = set()

        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                if event_type == "agent_message.delta":
                    delta = event.get("delta", "")
                    if delta:
                        deltas.append(delta)
                        yield delta
                elif event_type == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "agent_message":
                        text = item.get("text", "")
                        if text:
                            last_item_message = text
                elif event_type == "turn.completed":
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        self.last_usage = {
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                            "cached_input_tokens": usage.get("cached_input_tokens", 0),
                        }
                    if not deltas:
                        result = event.get("result", "")
                        if result:
                            fallback_result = result
                else:
                    if debug and event_type not in logged_unknown:
                        print(f"[solar-router][codex] unknown event: {event_type}", file=sys.stderr)
                        logged_unknown.add(event_type)

            proc.wait(timeout=timeout_sec)

            if not deltas:
                if last_item_message:
                    yield last_item_message
                elif fallback_result:
                    yield fallback_result

            if proc.returncode != 0:
                stderr = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr or "provider returned non-zero")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("provider timed out")
