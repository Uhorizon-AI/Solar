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

    def stream(self, prompt: str, *, review=None):
        """Default: single chunk via run(). Override for real streaming."""
        yield self.run(prompt, review=review)

    def run(self, prompt: str, *, review=None) -> str:
        if review is not None:
            return self.run_review(**review)
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

    def run_review(self, *, manifest, expected, profile, before_launch=lambda: None) -> str:
        """Restricted execution has one launch constructor and a fixed JSON output format."""
        import json
        from execution_profiles import restricted_launch
        self.last_usage = None
        with restricted_launch(self, manifest, expected, profile=profile,
                               before_launch=before_launch) as (argv, env, cwd):
            # Inherit the router's process group: the worker owns that group and
            # must stop the provider with it on timeout, cancellation or revocation.
            proc = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True,
                                  timeout=env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300))
            # The launch directory is removed on exit: read the final-message file now.
            last_message = None
            if self.name == "codex" and "--output-last-message" in argv:
                try:
                    with open(argv[argv.index("--output-last-message") + 1], encoding="utf-8") as fh:
                        last_message = fh.read()
                except (OSError, IndexError):
                    pass
        if proc.returncode:
            raise RuntimeError("restricted provider returned non-zero")
        if self.name == "codex":
            result = self._codex_final_review(proc.stdout, last_message)
        else:
            result = json.loads(proc.stdout)
        if not isinstance(result, dict):
            raise RuntimeError("restricted provider returned no result object")
        if self.name == "agy":
            if result.get("status") != "SUCCESS" or result.get("error"):
                raise RuntimeError("restricted provider returned an error")
            result = dict(result=result.get("response"), usage=result.get("usage"))
        elif self.name == "agent":
            if result.get("type") != "result" or result.get("subtype") != "success":
                raise RuntimeError("restricted provider returned an error")
            usage = result.get("usage")
            if isinstance(usage, dict) and "inputTokens" in usage:
                result["usage"] = dict(input_tokens=usage.get("inputTokens", 0),
                                       output_tokens=usage.get("outputTokens", 0),
                                       cached_input_tokens=usage.get("cacheReadTokens", 0))
        if result.get("is_error") or not isinstance(result.get("result"), str) or not result["result"]:
            raise RuntimeError("restricted provider returned no review text")
        self.last_usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
        if profile == "repository_readonly_v1":
            from execution_profiles import verify_envelope
            approved = verify_envelope(manifest, expected, provider=self.name, profile=profile)
            commit = json.loads(approved["user_prompt"])["commit"]
            return "Reviewed commit: " + commit + "\n\n" + result["result"]
        return result["result"]

    @staticmethod
    def _codex_final_review(stdout: str, last_message) -> dict:
        """Accept only the CLI's final-message file, validated against the requested schema.

        The JSONL stream has no field separating progress from the answer, so it is used
        for failure signals, the completed-turn marker and usage only; its text is never the review.
        """
        import json
        try:
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        except ValueError:
            raise RuntimeError("restricted provider returned malformed events") from None
        if not all(isinstance(event, dict) for event in events):
            raise RuntimeError("restricted provider returned malformed events")
        if any(event.get("type") in {"error", "turn.failed"} for event in events):
            raise RuntimeError("restricted provider returned an error")
        completed = [e for e in events if e.get("type") == "turn.completed"]
        if not completed:
            raise RuntimeError("restricted provider returned no completed review")
        if len(completed) > 1:
            raise RuntimeError("restricted provider returned more than one completed turn")
        try:
            final = json.loads(last_message) if last_message else None
        except ValueError:
            final = None
        if (not isinstance(final, dict) or set(final) != {"review"}
                or not isinstance(final["review"], str) or not final["review"].strip()):
            raise RuntimeError("restricted provider returned no structured final review")
        return dict(result=final["review"], usage=completed[0].get("usage"))

    def stream_review(self, **review):
        # Capture the result as text and consumption only, with the exact same
        # launch format as run. Transport streaming does not enable tool events.
        yield self.run_review(**review)
