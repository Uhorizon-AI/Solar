import json
import os
import shlex
import subprocess
import sys

from .base import BaseProvider, SOLAR_WORKSPACE, env_int


class CodexProvider(BaseProvider):
    name = "codex"
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        return f"codex exec --skip-git-repo-check --full-auto -C {SOLAR_WORKSPACE} --"

    def stream(self, prompt: str):
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
