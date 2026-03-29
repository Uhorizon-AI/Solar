import json
import os
import pathlib
import shlex
import subprocess
import sys

from .base import BaseProvider, REPO_ROOT

_CODEX_STATE_DIR = pathlib.Path.home() / ".codex"


class CodexProvider(BaseProvider):
    name = "codex"
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        # Use /tmp as working root so Codex does NOT auto-discover solar.ai as a
        # project and load AGENTS.md/profile.md/MEMORY.md on every call.
        # --add-dir gives Codex full read/write access to the repo when tasks need it.
        return (
            f"codex exec --skip-git-repo-check --full-auto -C /tmp "
            f"--add-dir {REPO_ROOT} --add-dir {_CODEX_STATE_DIR} --"
        )

    def stream(self, prompt: str):
        """Stream using `codex exec --json`, yielding text chunks as they arrive."""
        self.last_usage = None
        new_key = "SOLAR_ROUTER_CODEX_CMD"
        old_key = "SOLAR_AI_CODEX_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        parts = shlex.split(raw)
        if "--json" not in parts:
            if "--" in parts:
                # Keep provider options before `--` so codex treats them as flags, not prompt text.
                sep_idx = parts.index("--")
                parts.insert(sep_idx, "--json")
            else:
                parts.append("--json")
        parts[0] = self.resolve_binary(parts[0])
        cmd = parts + [prompt]

        env = self.prepare_env(os.environ.copy())
        timeout_sec = int(os.getenv("SOLAR_ROUTER_TIMEOUT_SEC") or "300")
        debug_events = os.getenv("SOLAR_ROUTER_CODEX_DEBUG_EVENTS", "").strip().lower() in {"1", "true", "yes", "on"}

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
        buffered_item_message: str | None = None
        seen_unknown_events: set[str] = set()

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

                # Some codex events wrap payload under `item`, e.g.
                # {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
                item = event.get("item")
                if isinstance(item, dict):
                    nested_text = item.get("text")
                    if isinstance(nested_text, str) and nested_text:
                        candidates.append(nested_text)

                    nested_message = item.get("message")
                    if isinstance(nested_message, dict):
                        for block in nested_message.get("content", []):
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

                event_type = str(event.get("type", ""))

                # Buffer item-completed assistant-style messages and only emit the latest one
                # when the turn ends. This avoids leaking intermediate "thinking/progress"
                # narration while still returning the final answer text.
                if event_type == "item.completed":
                    item = event.get("item")
                    if isinstance(item, dict):
                        item_type = str(item.get("type", ""))
                        if item_type in {"agent_message", "assistant_message", "message"}:
                            text = extract_text(event)
                            if text:
                                buffered_item_message = text
                                continue

                text = extract_text(event)
                if text:
                    full_text.append(text)
                    yield text
                    continue

                if event_type in {"turn.completed", "response.completed", "item.completed"}:
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        self.last_usage = usage
                    if event_type in {"turn.completed", "response.completed"} and buffered_item_message and not full_text:
                        yield buffered_item_message
                        full_text.append(buffered_item_message)
                        buffered_item_message = None
                    for key in ("text", "result", "output_text"):
                        value = event.get(key)
                        if isinstance(value, str) and value:
                            fallback_text = value
                            break
                elif debug_events and event_type not in {
                    "thread.started",
                    "turn.started",
                    "agent_message.delta",
                    "message.delta",
                    "response.output_text.delta",
                    "assistant_message.delta",
                    "agent_message",
                    "message",
                    "assistant_message",
                }:
                    if event_type not in seen_unknown_events:
                        seen_unknown_events.add(event_type)
                        snippet = json.dumps(event, ensure_ascii=False)[:400]
                        print(
                            f"[solar-router][codex] unhandled event type: {event_type} {snippet}",
                            file=sys.stderr,
                        )

            proc.wait(timeout=timeout_sec)
            if proc.returncode != 0:
                stderr = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr or "provider returned non-zero")
            if not full_text and fallback_text:
                yield fallback_text
                full_text.append(fallback_text)
            if not full_text and buffered_item_message:
                yield buffered_item_message
                full_text.append(buffered_item_message)
            if not full_text:
                stderr_hint = proc.stderr.read().strip()  # type: ignore[union-attr]
                raise RuntimeError(stderr_hint or "provider returned empty output")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("provider timed out")
