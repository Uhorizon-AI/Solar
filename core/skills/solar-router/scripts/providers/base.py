"""
BaseProvider — shared subprocess execution logic for all provider adapters.

Contract: run(prompt) -> str, stream(prompt) -> generator
"""
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
from abc import ABC
from typing import Dict, List

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1]
_INTERFACE_SCRIPTS = _SCRIPTS_DIR.parent.parent / "solar-interface" / "scripts"
if str(_INTERFACE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_INTERFACE_SCRIPTS))

from solar_paths import resolve_solar_paths  # noqa: E402

SOLAR_WORKSPACE, _SOLAR_ROOT = resolve_solar_paths()
FALLBACK_PATHS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(pathlib.Path.home() / ".local/bin"),
    "/usr/bin",
    "/bin",
]


class BaseProvider(ABC):
    name: str = ""
    default_cmd: str = ""

    def build_default_cmd(self) -> str:
        return self.default_cmd

    def resolve_binary(self, binary: str) -> str:
        found = shutil.which(binary)
        if found is None:
            current_path = os.getenv("PATH", "")
            merged = os.pathsep.join(FALLBACK_PATHS + ([current_path] if current_path else []))
            found = shutil.which(binary, path=merged)
        if found is None:
            env_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
            raise RuntimeError(
                f"client binary not found: {binary} "
                f"(provider={self.name}, env={env_key})"
            )
        return found

    def get_cmd(self, prompt: str) -> List[str]:
        new_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
        old_key = f"SOLAR_AI_{self.name.upper()}_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        parts = shlex.split(raw)
        if not parts:
            raise RuntimeError(f"{new_key} is empty")
        parts[0] = self.resolve_binary(parts[0])
        return parts + [prompt]

    def prepare_env(self, base_env: Dict[str, str]) -> Dict[str, str]:
        return base_env

    def clean_output(self, output: str) -> str:
        return output

    def get_cwd(self) -> pathlib.Path:
        """Run from SOLAR_WORKSPACE so CLIs auto-discover CLAUDE.md, GEMINI.md, profile.md, MEMORY.md."""
        return SOLAR_WORKSPACE

    def log_prompt(self, prompt: str, extra_flags: str = "") -> None:
        """Write prompt to sun/runtime/router/prompts.log when SOLAR_ROUTER_LOG_PROMPTS=true."""
        if os.getenv("SOLAR_ROUTER_LOG_PROMPTS", "false").lower() != "true":
            return
        new_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
        old_key = f"SOLAR_AI_{self.name.upper()}_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        entry = f"\n[solar-router][{self.name}] CMD: {raw}{extra_flags} <prompt>\n[PROMPT]\n{prompt}\n[/PROMPT]\n"
        print(entry, file=sys.stderr, flush=True)
        log_path = SOLAR_WORKSPACE / "sun/runtime/router/prompts.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)

    def stream(self, prompt: str):
        """Default: single chunk via run(). Override for real streaming."""
        yield self.run(prompt)

    def run(self, prompt: str) -> str:
        timeout_sec = int(os.getenv("SOLAR_ROUTER_TIMEOUT_SEC") or "300")
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
        if proc.returncode != 0:
            error = proc.stderr.strip() or proc.stdout.strip() or "provider returned non-zero"
            raise RuntimeError(error)
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("provider returned empty output")
        return self.clean_output(output)
