"""
BaseProvider — shared subprocess execution logic for all provider adapters.

Each subclass must set `name` and either `default_cmd` (str) or override
`build_default_cmd()` for providers whose command depends on runtime paths.

Contract: run(prompt) -> str
  - Returns normalized stdout on success.
  - Raises RuntimeError with a clear message on any failure.
  - Never swallows errors silently.
"""
import os
import pathlib
import shlex
import shutil
import subprocess
from abc import ABC
from typing import Dict, List

# providers/base.py lives at core/skills/solar-router/scripts/providers/
# parents: [0] providers/  [1] scripts/  [2] solar-router/  [3] skills/  [4] core/  [5] repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
FALLBACK_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]


class BaseProvider(ABC):
    """Abstract base for provider adapters. Subclasses set name + default_cmd."""

    name: str = ""
    default_cmd: str = ""

    def build_default_cmd(self) -> str:
        """Override in subclasses whose default command is computed at runtime."""
        return self.default_cmd

    def resolve_binary(self, binary: str) -> str:
        """Return the absolute path to `binary`, searching FALLBACK_PATHS if needed."""
        found = shutil.which(binary)
        if found is None:
            current_path = os.getenv("PATH", "")
            merged = os.pathsep.join(FALLBACK_PATHS + ([current_path] if current_path else []))
            found = shutil.which(binary, path=merged)
        if found is None:
            env_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
            raise RuntimeError(
                f"client binary not found: {binary} "
                f"(provider={self.name}, env={env_key}, PATH={os.getenv('PATH', '')})"
            )
        return found

    def get_cmd(self, prompt: str) -> List[str]:
        """Build the full command list for this provider, including prompt."""
        new_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
        old_key = f"SOLAR_AI_{self.name.upper()}_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        parts = shlex.split(raw)
        if not parts:
            raise RuntimeError(f"{new_key} is empty")
        parts[0] = self.resolve_binary(parts[0])
        return parts + [prompt]

    def prepare_env(self, base_env: Dict[str, str]) -> Dict[str, str]:
        """Return env dict for subprocess. Override to inject provider-specific vars."""
        return base_env

    def clean_output(self, output: str) -> str:
        """Normalize raw stdout. Override to strip ANSI codes or detect error patterns."""
        return output

    def run(self, prompt: str) -> str:
        """Execute the provider and return its output string.

        Raises RuntimeError on non-zero exit, empty output, or output that
        indicates a non-recoverable provider error (e.g. OAuth prompt).
        """
        timeout_sec = int(os.getenv("SOLAR_ROUTER_TIMEOUT_SEC") or "300")
        cmd = self.get_cmd(prompt)
        env = self.prepare_env(os.environ.copy())
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            cwd=REPO_ROOT,
            env=env,
        )
        if proc.returncode != 0:
            error = proc.stderr.strip() or proc.stdout.strip() or "provider returned non-zero"
            raise RuntimeError(error)
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("provider returned empty output")
        return self.clean_output(output)
