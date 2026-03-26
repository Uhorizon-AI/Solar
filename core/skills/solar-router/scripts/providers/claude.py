import json
import os
import shlex
import subprocess

from .base import BaseProvider, REPO_ROOT


class ClaudeProvider(BaseProvider):
    name = "claude"
    default_cmd = "claude -p --permission-mode bypassPermissions --no-session-persistence"

    def stream(self, prompt: str):
        """Stream token-by-token using --include-partial-messages, yielding text_delta chunks."""
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
                if event_type == "stream_event":
                    # Token-level deltas from --include-partial-messages
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                full_text.append(text)
                                yield text
                elif event_type == "result" and not full_text:
                    # Fallback: result field when no stream_event deltas produced text
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
