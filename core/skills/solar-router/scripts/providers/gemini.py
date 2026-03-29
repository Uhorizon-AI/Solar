import json
import os
import re
import shlex
import subprocess

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_cmd = "gemini -y"
    last_usage: dict | None = None

    def clean_output(self, output: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        if (
            "Please visit the following URL to authorize the application" in cleaned
            or "Enter the authorization code:" in cleaned
        ):
            raise RuntimeError(
                "gemini returned OAuth prompt in headless mode; "
                "credentials are not usable for non-interactive execution"
            )
        return cleaned

    def stream(self, prompt: str):
        """Stream using --output-format stream-json."""
        self.log_prompt(prompt, " --output-format stream-json")
        new_key = "SOLAR_ROUTER_GEMINI_CMD"
        old_key = "SOLAR_AI_GEMINI_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.default_cmd).strip()
        if "--output-format" not in raw:
            raw += " --output-format stream-json"
        parts = shlex.split(raw)
        while "-p" in parts:
            parts.remove("-p")
        while "--prompt" in parts:
            parts.remove("--prompt")
        parts[0] = self.resolve_binary(parts[0])
        cmd = parts + ["-p", prompt]

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
                    self.clean_output(line)
                    continue

                event_type = event.get("type")
                if event_type == "message" and event.get("role") == "assistant":
                    text = event.get("content", "")
                    if text:
                        full_text.append(text)
                        yield text
                elif event_type == "result":
                    stats = event.get("stats")
                    if isinstance(stats, dict):
                        self.last_usage = {
                            "input_tokens": stats.get("input_tokens", 0),
                            "output_tokens": stats.get("output_tokens", 0),
                            "cached_input_tokens": stats.get("cached", 0),
                        }
                    if not full_text:
                        result = event.get("result", "")
                        if result:
                            full_text.append(result)
                            yield result
                elif not full_text and event_type not in {"message", "result", "progress"}:
                    text = event.get("text") or event.get("content") or ""
                    if text and isinstance(text, str):
                        full_text.append(text)
                        yield text

            proc.wait(timeout=timeout_sec)
            if proc.returncode != 0:
                stderr = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr or "provider returned non-zero")
            if not full_text:
                stderr_hint = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr_hint or "provider returned empty output")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("provider timed out")
