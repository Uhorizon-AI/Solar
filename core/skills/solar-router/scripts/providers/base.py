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
_PATHS_SCRIPTS = _SCRIPTS_DIR.parent.parent / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))

import solar_runtime  # noqa: E402
from solar_paths import resolve_solar_paths  # noqa: E402

SOLAR_WORKSPACE, SOLAR_ROOT = resolve_solar_paths()


def _runtime_router_dir() -> pathlib.Path:
    """Router machine state: explicit override, else the framework runtime root."""
    raw = os.getenv("SOLAR_ROUTER_RUNTIME_DIR") or os.getenv("SOLAR_RUNTIME_DIR") or ""
    if raw:
        path = pathlib.Path(raw)
        return path if path.is_absolute() else SOLAR_WORKSPACE / path
    return solar_runtime.runtime_dir("router")
FALLBACK_PATHS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(pathlib.Path.home() / ".local/bin"),
    "/usr/bin",
    "/bin",
]


def env_int(name: str, default: int) -> int:
    """Parse int env vars allowing inline comments (e.g. '3600 # note')."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = raw.split("#", 1)[0].strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"invalid integer env {name}={raw!r} (expected e.g. {default})"
        ) from exc


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
        """Tell the provider where it is, before it has to guess.

        It runs from SOLAR_WORKSPACE (get_cwd), and the framework is not inside
        it: a prompt that names `core/skills/...` resolves nowhere from that
        directory. A subtask hit this on 2026-09-20 and asked which path to use
        instead of reading the file. The router already resolved both paths at
        import and kept them to itself; passing them down is what makes such a
        path openable. An exported value wins: a caller that redirected the
        workspace meant it.
        """
        base_env.setdefault("SOLAR_WORKSPACE", str(SOLAR_WORKSPACE))
        base_env.setdefault("SOLAR_ROOT", str(SOLAR_ROOT))
        return base_env

    def clean_output(self, output: str) -> str:
        return output

    def get_cwd(self) -> pathlib.Path:
        """Run from SOLAR_WORKSPACE so CLIs auto-discover CLAUDE.md, GEMINI.md, profile.md, MEMORY.md."""
        return SOLAR_WORKSPACE

    def log_prompt(self, prompt: str, extra_flags: str = "") -> None:
        """Write prompt to <runtime root>/router/prompts.log when SOLAR_ROUTER_LOG_PROMPTS=true."""
        if os.getenv("SOLAR_ROUTER_LOG_PROMPTS", "false").lower() != "true":
            return
        new_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
        old_key = f"SOLAR_AI_{self.name.upper()}_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        entry = f"\n[solar-router][{self.name}] CMD: {raw}{extra_flags} <prompt>\n[PROMPT]\n{prompt}\n[/PROMPT]\n"
        print(entry, file=sys.stderr, flush=True)
        log_path = _runtime_router_dir() / "prompts.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)

    def stream(self, prompt: str):
        """Default: single chunk via run(). Override for real streaming."""
        yield self.run(prompt)

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
        if proc.returncode != 0:
            error = proc.stderr.strip() or proc.stdout.strip() or "provider returned non-zero"
            raise RuntimeError(error)
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("provider returned empty output")
        return self.clean_output(output)
