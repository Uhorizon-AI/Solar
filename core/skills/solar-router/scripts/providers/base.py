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
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_PATHS_SCRIPTS = _SCRIPTS_DIR.parent.parent / "solar-paths" / "scripts"
if str(_PATHS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PATHS_SCRIPTS))

import solar_runtime  # noqa: E402
from cli_permissions import MCP_READ_TOOLS  # noqa: E402
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


@dataclass(frozen=True)
class AskResult:
    """What a client answered to a question, and how it was asked to behave."""

    provider: str
    text: str
    mode: str  # the client's native read-only switch, or "none" when it has none


def raise_restricted_failure(provider_name: str, failure: str | None, returncode: int):
    """Turn a restricted reader's non-zero exit into the error the router reports.

    Cursor's EPERM mkdir of `/tmp/.cursor…` is the write guard denying the
    project-state directory. Redaction hides the slug as `/tmp/.[REDACTED]`.
    Any other denied mkdir stays a generic failure so a different cause is
    not labeled as the project-path fallback. The preflight mkdir reports
    `cursor_state_mkdir_denied` or `cursor_state_mkdir_timeout` itself.
    """
    text = failure or ""
    cursor_tmp = "/tmp/.cursor" in text or "/tmp/.[REDACTED]" in text
    if provider_name == "agent" and "EPERM" in text and "mkdir" in text and cursor_tmp:
        from execution_profiles import ProfileError
        raise ProfileError("execution_profile_unsupported", detail=dict(
            provider="agent", stage="state", reason="cursor_project_path_outside_write_guard"))
    raise RuntimeError("restricted provider returned non-zero (" + (failure or f"exit {returncode}") + ")")


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

    def read_only_args(self, cwd: pathlib.Path) -> Tuple[List[str], str]:
        """The client's native read-only switches and their label; none by default."""
        return [], "none"

    def static_permission_checks(self, home: pathlib.Path, workspace: pathlib.Path) -> list:
        """Findings read from the client's own settings, without a model call.

        Checks a client has no readable settings for are left out; the caller reports
        them as `unknown`. Never writes to the client's configuration.
        """
        return []

    def permission_fix_hint(self, check: str) -> str:
        return {"mcp_read": f"allow the Solar MCP read tools ({', '.join(MCP_READ_TOOLS)}) in the client's own permission settings",
                "write_guard": "make the client's own settings stop overriding its read-only mode"}[check]

    def ask(self, prompt: str, *, cwd=None, model: Optional[str] = None, observer=None) -> AskResult:
        """Put one question to the client with the session the user logged in with.

        The environment is the caller's own: HOME and the client's config
        directory are not replaced and no credential is copied or linked, so the
        client finds its login where it always does. Read-only is a request made
        in the client's own terms, not a guarantee; `mode` says what was asked.

        A `SOLAR_ROUTER_<NAME>_CMD` override contributes only the binary: its own flags are not used,
        `ask_prefix()` and `read_only_args()` are imposed. The prompt always follows a separator.
        """
        start = pathlib.Path(cwd) if cwd else self.get_cwd()
        flags, mode = self.read_only_args(start)
        new_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
        old_key = f"SOLAR_AI_{self.name.upper()}_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        parts = shlex.split(raw)
        if not parts:
            raise RuntimeError(f"{new_key} is empty")
        cmd = [self.resolve_binary(parts[0]), *self.ask_prefix(), *flags,
               *(["--model", model] if model else []),
               *(self._measurement_flags() if observer is not None else []), *self.ask_separator(), prompt]
        env = self.prepare_env(os.environ.copy())
        self.log_prompt(prompt)
        if observer is not None:
            from ask_metering import run
            try:
                output = run(self.name, cmd, cwd=start, env=env,
                             timeout=env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300), observer=observer)
            except (TimeoutError, subprocess.TimeoutExpired):
                raise TimeoutError(f"{self.name} exit timeout") from None
            return AskResult(self.name, self.clean_output(output), mode)
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True,
                                  timeout=env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300), cwd=start, env=env)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{self.name} exit timeout") from None
        if proc.returncode != 0:
            from review_failure import summarize
            raise RuntimeError(f"{self.name} {summarize(proc.returncode, proc.stderr or '', proc.stdout or '', prompts=[prompt])}")
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("provider returned empty output")
        return AskResult(self.name, self.clean_output(output), mode)

    def _measurement_flags(self):
        from ask_metering import output_flags
        return output_flags(self.name)

    def ask_prefix(self) -> List[str]:
        """Non-interactive entry switches of the client, before the read-only ones."""
        return []

    def ask_separator(self) -> List[str]:
        return []

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

    def run_review(self, *, manifest, expected, profile, before_launch=lambda: None, observation_sink=None) -> str:
        """Restricted execution has one launch constructor and a fixed JSON output format."""
        import json
        from execution_profiles import restricted_launch, ASK_PROFILE
        self.last_usage = None
        if profile == ASK_PROFILE:
            return self._run_ask_profile(manifest, expected, before_launch, observation_sink)
        with restricted_launch(self, manifest, expected, profile=profile,
                               before_launch=before_launch) as (argv, env, cwd):
            # Inherit the router's process group: the worker owns that group and
            # must stop the provider with it on timeout, cancellation or revocation.
            try:
                proc = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True,
                                      timeout=env_int("SOLAR_ROUTER_TIMEOUT_SEC", 300))
            except subprocess.TimeoutExpired as exc:
                # The client was running when the deadline hit: it was launched. An exec failure
                # (missing binary, no permission) raises before this point and stays "not launched".
                self._confirm_launch(observation_sink, argv)
                self._capture_evidence(manifest, argv, env, exc.stdout, None, timed_out=True)
                raise
            self._confirm_launch(observation_sink, argv)
            # Opt-in diagnostic copy, taken before the launch directory is removed.
            self._capture_evidence(manifest, argv, env, proc.stdout, proc.returncode)
            failure = self._failure_reason(argv, proc) if proc.returncode else None
            # The launch directory is removed on exit: read the final-message file now.
            last_message = None
            if self.name == "codex" and "--output-last-message" in argv:
                try:
                    with open(argv[argv.index("--output-last-message") + 1], encoding="utf-8") as fh:
                        last_message = fh.read()
                except (OSError, ValueError, IndexError):  # ValueError: non-UTF-8 bytes
                    pass
        try:
            if proc.returncode:
                raise_restricted_failure(self.name, failure, proc.returncode)
            if self.name == "codex":
                result = self._codex_final_review(proc.stdout, last_message)
            else:
                result = json.loads(proc.stdout)
            if not isinstance(result, dict):
                raise RuntimeError("restricted provider returned no result object")
            # The client's own record and counters, kept before any normalization: absent stays absent, never zero.
            native_result = dict(result)
            native_usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
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
        except Exception:
            self._record_rejected_counters(observation_sink, proc.stdout)
            raise
        self.last_usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
        if observation_sink is not None:
            # The restricted launch already returns the client's own final record: record its counters
            # as the terminal observation. A reply without counters still closes as "no counters".
            from ask_metering import review_observation
            observation_sink(1, review_observation(self.name, native_result, native_usage))
        if profile == "repository_readonly_v1":
            from execution_profiles import verify_envelope
            approved = verify_envelope(manifest, expected, provider=self.name, profile=profile)
            commit = json.loads(approved["user_prompt"])["commit"]
            from repository_reviews import freshness_line
            return ("Reviewed commit: " + commit + "\n" + freshness_line(approved) + "\n\n"
                    + result["result"])
        return result["result"]

    def _confirm_launch(self, observation_sink, argv) -> None:
        """Tell the meter the client process really started.

        A meter that cannot persist this is flagged (the sink records the problem) but never replaces
        the outcome of a review that already ran, or that already timed out."""
        if observation_sink is not None:
            try:
                observation_sink.launched(argv[0], (getattr(self, "last_review_preflight", None) or {}).get("version"))
            except Exception:  # noqa: BLE001
                observation_sink.capture_problem("persistence_failed")

    def _record_rejected_counters(self, observation_sink, stdout) -> None:
        """Counters a rejected reply still carried: evidence of a failed attempt, never validated metrics.

        Best effort: whatever the client printed that is not parseable is simply not evidence.
        """
        if observation_sink is None:
            return
        import json
        try:
            if self.name == "codex":
                events = []
                for line in (stdout or "").splitlines():
                    try:  # one truncated line must not discard the counters of the valid ones
                        events.append(json.loads(line))
                    except ValueError:
                        continue
                usage = [e["usage"] for e in events if isinstance(e, dict) and isinstance(e.get("usage"), dict)]
                record, usage = {}, (usage[-1] if usage else None)
            else:
                record = json.loads(stdout)
                usage = record.get("usage") if isinstance(record, dict) else None
                record = record if isinstance(record, dict) else {}
            from ask_metering import review_observation
            observation = review_observation(self.name, record, usage, successful=False)
            if "usage" in observation or "model_usage" in observation:
                observation_sink(1, observation)
        except Exception:  # noqa: BLE001  # the original failure is what the caller must see
            observation_sink.capture_problem("persistence_failed")

    def _run_ask_profile(self, manifest, expected, before_launch, observation_sink=None) -> str:
        """A question: verified twice around the launch, answered with the client's own session."""
        from execution_profiles import verify_envelope, ask_prompt, ask_cwd, ASK_PROFILE
        approved = verify_envelope(manifest, expected, provider=self.name, profile=ASK_PROFILE)
        before_launch()
        kwargs = dict(cwd=ask_cwd(approved), model=approved.get("model"))
        if observation_sink is not None:
            kwargs["observer"] = observation_sink
        answer = self.ask(ask_prompt(approved), **kwargs)
        self.last_review_preflight = dict(provider=self.name, read_only_mode=answer.mode)
        return answer.text

    @staticmethod
    def _failure_reason(argv, proc) -> str:
        """Short redacted reason from stderr and, for Antigravity, its private log (read before the
        launch directory is removed). Never raises."""
        try:
            from review_failure import summarize
            log = ""
            if "--log-file" in argv:
                try:
                    with open(argv[argv.index("--log-file") + 1], encoding="utf-8", errors="replace") as fh:
                        log = fh.read()[-20000:]
                except (OSError, IndexError):
                    pass
            prompts = [a for a in argv if isinstance(a, str) and len(a) >= 20]
            return summarize(proc.returncode, proc.stderr or "", log, prompts=prompts)
        except Exception:  # noqa: BLE001
            return f"exit {proc.returncode}"

    def _capture_evidence(self, manifest, argv, env, stdout, returncode, timed_out=False) -> None:
        """Diagnostic only: any failure here, import included, must not change the outcome."""
        if self.name != "codex":
            return
        try:
            import json
            from review_evidence import capture_codex
            try:
                commit = json.loads(manifest["user_prompt"])["commit"]
            except (KeyError, TypeError, ValueError):
                commit = None
            capture_codex(argv, env, stdout, returncode, timed_out=timed_out, commit=commit)
        except Exception as exc:  # noqa: BLE001
            if (os.getenv("SOLAR_ROUTER_REVIEW_EVIDENCE_DIR") or "").strip():
                try:  # enabled capture that cannot run must not go unnoticed
                    print("[solar-router] review evidence not captured: " + type(exc).__name__,
                          file=sys.stderr)
                except Exception:  # noqa: BLE001
                    pass

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
