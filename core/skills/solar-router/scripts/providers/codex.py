import json
import os
import pathlib
import shlex
import subprocess

from .base import BaseProvider, REPO_ROOT

_CODEX_STATE_DIR = pathlib.Path.home() / ".codex"


class CodexProvider(BaseProvider):
    name = "codex"

    def build_default_cmd(self) -> str:
        return (
            f"codex exec --skip-git-repo-check --full-auto -C {REPO_ROOT} "
            f"--add-dir {_CODEX_STATE_DIR} --"
        )

    def stream(self, prompt: str):
        """Stream using `codex exec --json`, yielding text chunks as they arrive."""
        new_key = "SOLAR_ROUTER_CODEX_CMD"
        old_key = "SOLAR_AI_CODEX_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        if "--json" not in raw:
            raw += " --json"
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
        fallback_text: str | None = None

        def extract_text(event: dict) -> str:
            candidates: list[str] = []
            event_type = str(event.get("type", ""))

            if event_type in {
                "agent_message.delta",
                "message.delta",
                "response.output_text.delta",
                "assistant_message.delta",
            }:
                for key in ("delta", "text"):
                    value = event.get(key)
                    if isinstance(value, str) and value:
                        candidates.append(value)

            if event_type in {
                "agent_message",
                "message",
                "item.completed",
                "response.completed",
                "assistant_message",
            }:
                value = event.get("text")
                if isinstance(value, str) and value:
                    candidates.append(value)

                message = event.get("message")
                if isinstance(message, dict):
                    for block in message.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                candidates.append(text)

            if not candidates:
                value = event.get("text")
                if isinstance(value, str) and value and not event_type.startswith(("thread.", "turn.")):
                    candidates.append(value)

            return "".join(candidates)

        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                text = extract_text(event)
                if text:
                    full_text.append(text)
                    yield text
                    continue

                event_type = str(event.get("type", ""))
                if event_type in {"turn.completed", "response.completed", "item.completed"}:
                    for key in ("text", "result", "output_text"):
                        value = event.get(key)
                        if isinstance(value, str) and value:
                            fallback_text = value
                            break

            proc.wait(timeout=timeout_sec)
            if proc.returncode != 0:
                stderr = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr or "provider returned non-zero")
            if not full_text and fallback_text:
                yield fallback_text
                full_text.append(fallback_text)
            if not full_text:
                raise RuntimeError("provider returned empty output")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("provider timed out")
