import os
import re
import subprocess

from .base import BaseProvider, env_int


class OllamaProvider(BaseProvider):
    name = "ollama"
    last_usage: dict | None = None

    _ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
    _CONTROL_RE = re.compile(r"[\r\b]")
    _SPINNER_LINE_RE = re.compile(r"^\s*[⠁-⣿]+\s*$", re.MULTILINE)

    def build_default_cmd(self) -> str:
        return "ollama run solar --hidethinking --nowordwrap"

    def clean_output(self, output: str) -> str:
        cleaned = self._ANSI_RE.sub("", output)
        cleaned = self._CONTROL_RE.sub("", cleaned)
        cleaned = self._SPINNER_LINE_RE.sub("", cleaned)

        # Remove short spinner/progress fragments left after ANSI stripping.
        cleaned_lines = []
        for line in cleaned.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if all(ch in "⠁⠂⠃⠄⠅⠆⠇⠈⠉⠊⠋⠌⠍⠎⠏⠐⠑⠒⠓⠔⠕⠖⠗⠘⠙⠚⠛⠜⠝⠞⠟⠠⠡⠢⠣⠤⠥⠦⠧⠨⠩⠪⠫⠬⠭⠮⠯⠰⠱⠲⠳⠴⠵⠶⠷⠸⠹⠺⠻⠼⠽⠾⠿ " for ch in stripped):
                continue
            cleaned_lines.append(line.rstrip())

        cleaned = "\n".join(cleaned_lines).strip()

        if "failed to connect to ollama" in cleaned.lower() or "127.0.0.1:11434" in cleaned:
            raise RuntimeError(
                "ollama daemon unavailable; start it with `ollama serve` or check OLLAMA_HOST"
            )

        if "model" in cleaned.lower() and "not found" in cleaned.lower():
            raise RuntimeError(cleaned)

        return cleaned

    def run(self, prompt: str) -> str:
        timeout_sec = env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300)
        cmd = self.get_cmd(prompt)
        env = self.prepare_env(os.environ.copy())
        self.log_prompt(prompt)
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            cwd=self.get_cwd(),
            env=env,
        )
        stdout = self.clean_output(proc.stdout or "")
        stderr = self.clean_output(proc.stderr or "")
        if proc.returncode != 0:
            error = stderr or stdout or "provider returned non-zero"
            raise RuntimeError(error)
        if not stdout:
            raise RuntimeError("provider returned empty output")
        return stdout
