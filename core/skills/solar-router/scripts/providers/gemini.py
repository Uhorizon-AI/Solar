import json
import os
import pathlib
import re
import shlex
import subprocess
from typing import Dict

from .base import BaseProvider, REPO_ROOT


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_cmd = "gemini -y"

    def prepare_env(self, base_env: Dict[str, str]) -> Dict[str, str]:
        env = base_env.copy()
        env.setdefault("GEMINI_CLI_HOME", str(pathlib.Path.home()))
        env.setdefault("GEMINI_FORCE_ENCRYPTED_FILE_STORAGE", "false")
        return env

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
        """Stream using --output-format stream-json, yielding text chunks as they arrive."""
        new_key = "SOLAR_ROUTER_GEMINI_CMD"
        old_key = "SOLAR_AI_GEMINI_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.default_cmd).strip()
        if "--output-format" not in raw:
            raw += " --output-format stream-json"
        parts = shlex.split(raw)
        
        # Limpiar cualquier "-p" o "--prompt" suelto que carezca de parámetro asociado
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
                    # Validar si saltó el prompt the OAuth silenciosamente
                    self.clean_output(line)
                    continue

                event_type = event.get("type")
                if event_type == "message" and event.get("role") == "assistant":
                    text = event.get("content", "")
                    if text:
                        full_text.append(text)
                        yield text
                elif event_type == "result" and not full_text:
                    # Fallback: result field when no assistant events produced text
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
