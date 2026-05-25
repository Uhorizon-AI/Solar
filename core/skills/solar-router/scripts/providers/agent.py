import json
import os
import shlex
import subprocess

from .base import BaseProvider, SOLAR_WORKSPACE


class AgentProvider(BaseProvider):
    name = "agent"
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        return f"agent -p -f --approve-mcps -C {SOLAR_WORKSPACE}"

    def stream(self, prompt: str):
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
        timeout_sec = int(os.getenv("SOLAR_ROUTER_TIMEOUT_SEC") or "300")

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
