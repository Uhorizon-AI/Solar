#!/usr/bin/env python3
"""
execute_active.py — Python executor for solar-async-tasks.

Handles I/O JSON with solar-router v3. Called by execute_active.sh.
- Reads task file path and task metadata from arguments/env
- Builds router v3 request (channel=async-task, mode=direct_only)
- Passes provider from task frontmatter if set (strict mode)
- Parses router v3 JSON response
- Writes structured log and returns exit code for lifecycle management

Usage:
    python3 execute_active.py <task_file> <router_script> <task_id> <title>
"""
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Interpreters allowed as argv[0] when local_command runs a script under workspace.
_LOCAL_INTERPRETERS = frozenset({"bash", "sh", "python3", "python", "ruby"})

# Exact relative patterns under SOLAR_WORKSPACE (posix), after resolve().
_LOCAL_SCRIPT_PATTERNS = (
    re.compile(r"^planets/[^/]+/skills/[^/]+/scripts/.+"),
    re.compile(r"^solar/core/skills/[^/]+/scripts/.+"),
    re.compile(r"^core/skills/[^/]+/scripts/.+"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_local_timeout(raw: str) -> Tuple[Optional[int], Optional[str]]:
    """Return (seconds, error_code). error_code set ⇒ fail-closed."""
    value = (raw or "300").strip() or "300"
    try:
        timeout_sec = int(value)
    except ValueError:
        return None, "local_timeout_invalid"
    if timeout_sec <= 0:
        return None, "local_timeout_invalid"
    return timeout_sec, None


def authorize_local_argv(
    local_command: str, workspace: pathlib.Path
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Tokenize and allowlist local_command under skill script trees only.

    Allowed relative paths (after resolve, posix):
      planets/<planet>/skills/<skill>/scripts/**
      solar/core/skills/<skill>/scripts/**
      core/skills/<skill>/scripts/**

    Returns (argv, error_code). error_code set ⇒ refuse execution.
    """
    try:
        argv = shlex.split(local_command)
    except ValueError:
        return None, "local_command_invalid"
    if not argv:
        return None, "local_command_missing"

    script_idx = 0
    first_name = pathlib.Path(argv[0]).name
    if first_name in _LOCAL_INTERPRETERS:
        if len(argv) < 2:
            return None, "local_command_unauthorized"
        script_idx = 1

    script_token = argv[script_idx]
    script_path = pathlib.Path(script_token)
    if not script_path.is_absolute():
        script_path = (workspace / script_path).resolve()
    else:
        script_path = script_path.resolve()

    try:
        rel = script_path.relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return None, "local_command_unauthorized"

    if not any(pat.match(rel) for pat in _LOCAL_SCRIPT_PATTERNS):
        return None, "local_command_unauthorized"
    if not script_path.is_file():
        return None, "local_command_missing"

    argv = list(argv)
    argv[script_idx] = str(script_path)
    return argv, None


def read_frontmatter_key(task_file: pathlib.Path, key: str) -> str:
    """Extract a single frontmatter key value from a markdown file."""
    in_fm = False
    for line in task_file.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm and line.startswith(f"{key}:"):
            value = line[len(f"{key}:"):].strip().strip('"')
            return value
    return ""


def strip_frontmatter(task_file: pathlib.Path) -> str:
    """Return task body with frontmatter removed."""
    lines = task_file.read_text(encoding="utf-8").splitlines()
    in_fm = False
    fm_done = False
    body_lines = []
    for line in lines:
        if not fm_done:
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                    continue
                else:
                    fm_done = True
                    continue
            elif not in_fm:
                fm_done = True
                body_lines.append(line)
        else:
            body_lines.append(line)
    return "\n".join(body_lines).strip()


def build_prompt(task_id: str, title: str, body: str) -> str:
    return (
        "You are executing a Solar asynchronous task.\n"
        "Follow the task instructions exactly as written in the task body.\n"
        "If the task asks to act as an agent and use a skill, do so.\n\n"
        f"Task ID: {task_id}\n"
        f"Task Title: {title}\n\n"
        f"Task Body:\n{body}"
    )


def _env_int_with_comment(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = raw.split("#", 1)[0].strip()
    if not value:
        return default
    return int(value)


def call_router(
    router_script: pathlib.Path,
    task_id: str,
    prompt: str,
    provider: Optional[str],
) -> Dict[str, Any]:
    """
    Call solar-router v3 with channel=async-task, mode=direct_only.
    Returns parsed router v3 response dict.
    """
    router_python = os.getenv("SOLAR_AI_ROUTER_PYTHON", "python3")
    timeout_sec = _env_int_with_comment(
        "SOLAR_ROUTER_TIMEOUT_SEC",
        _env_int_with_comment("SOLAR_AI_ROUTER_TIMEOUT_SEC", 310),
    )

    payload: Dict[str, Any] = {
        "request_id": f"task_{task_id}",
        "session_id": f"task_{task_id}",
        "user_id": "solar-async-tasks",
        "text": prompt,
        "channel": "async-task",
        "mode": "direct_only",
    }
    if provider:
        payload["provider"] = provider

    proc = subprocess.run(
        [router_python, str(router_script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )

    stdout = proc.stdout.strip()

    # Always try to parse stdout as router v3 JSON first — even on non-zero exit.
    # Router emits structured JSON errors (with real error_code) and then exits 1.
    if stdout:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            pass

    # Fallback: no parseable JSON at all (crash, binary not found, etc.)
    error_msg = proc.stderr.strip() or stdout or "router crashed with no output"
    return {
        "status": "failed",
        "request_id": f"task_{task_id}",
        "provider_used": provider,
        "reply_text": "",
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "error_code": "router_crashed",
        "error": error_msg,
    }


def write_log(
    log_file: pathlib.Path,
    task_id: str,
    title: str,
    outcome: str,
    provider_used: Optional[str],
    result_text: str,
    error_text: Optional[str],
    error_code: Optional[str],
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Async Task Execution",
        "",
        f"- outcome: {outcome}",
        f"- task_id: {task_id}",
        f"- title: {title}",
        f"- executed_at: {utc_now()}",
        f"- provider_used: {provider_used or 'unknown'}",
        "",
    ]
    if outcome == "success":
        lines += ["## Result", "", result_text]
    else:
        lines += [
            "## Error",
            "",
            f"- error_code: {error_code or 'unknown'}",
            f"- error: {error_text or 'unknown'}",
        ]
    log_file.write_text("\n".join(lines), encoding="utf-8")


def mark_task_error(
    task_file: pathlib.Path,
    task_id: str,
    title: str,
    provider_used: Optional[str],
    error_code: Optional[str],
    error_text: str,
    log_file: pathlib.Path,
) -> None:
    """Update task frontmatter status to error and move to error/ dir."""
    content = task_file.read_text(encoding="utf-8")
    content = re.sub(r"^status:.*$", "status: error", content, flags=re.MULTILINE)
    err_ts = utc_now()
    content += (
        f"\n\n## Execution Error\n"
        f"- time: {err_ts}\n"
        f"- provider_attempted: {provider_used or 'unknown'}\n"
        f"- error_code: {error_code or 'unknown'}\n"
        f"- error: {error_text}\n"
    )
    task_file.write_text(content, encoding="utf-8")

    write_log(log_file, task_id, title, "error", provider_used, "", error_text, error_code)

    error_dir = task_file.parent.parent / "error"
    error_dir.mkdir(parents=True, exist_ok=True)
    dest = error_dir / task_file.name
    task_file.rename(dest)
    print(f"❌ Task execution failed and moved to error/: {task_id}", flush=True)
    print(f"   Log: {log_file}", flush=True)


def main() -> int:
    if len(sys.argv) < 5:
        print(
            "Usage: execute_active.py <task_file> <router_script> <task_id> <title>",
            file=sys.stderr,
        )
        return 1

    task_file = pathlib.Path(sys.argv[1])
    router_script = pathlib.Path(sys.argv[2])
    task_id = sys.argv[3]
    title = sys.argv[4]

    if not task_file.exists():
        print(f"Error: task file not found: {task_file}", file=sys.stderr)
        return 1

    # Derive log path
    task_root = task_file.parent.parent
    log_dir = task_root / "logs"
    log_file = log_dir / (task_file.stem + ".log")

    # Read per-task provider override from frontmatter
    task_provider = read_frontmatter_key(task_file, "provider").strip().lower() or None
    executor = read_frontmatter_key(task_file, "executor").strip().lower()

    if executor == "local":
        local_command = read_frontmatter_key(task_file, "local_command").strip()
        if not local_command:
            mark_task_error(
                task_file, task_id, title, "local",
                "local_command_missing", "executor=local requires local_command", log_file
            )
            return 1
        workspace = pathlib.Path(
            os.getenv("SOLAR_WORKSPACE") or task_root.parent.parent.parent
        ).resolve()
        timeout_sec, timeout_err = parse_local_timeout(
            read_frontmatter_key(task_file, "local_timeout")
        )
        if timeout_err:
            mark_task_error(
                task_file, task_id, title, "local",
                timeout_err, f"invalid local_timeout: {read_frontmatter_key(task_file, 'local_timeout')!r}",
                log_file,
            )
            return 1
        argv, auth_err = authorize_local_argv(local_command, workspace)
        if auth_err or not argv:
            mark_task_error(
                task_file, task_id, title, "local",
                auth_err or "local_command_unauthorized",
                f"local_command not authorized under workspace scripts/: {local_command}",
                log_file,
            )
            return 1
        print(f"  Running approved local executor: {local_command}", flush=True)
        try:
            proc = subprocess.run(
                argv,
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            mark_task_error(
                task_file, task_id, title, "local",
                "local_timeout", f"local command timed out after {timeout_sec}s", log_file
            )
            return 1
        except Exception as exc:
            mark_task_error(
                task_file, task_id, title, "local",
                "local_exception", str(exc), log_file
            )
            return 1

        output = "\n".join(
            part.strip() for part in (proc.stdout, proc.stderr) if part.strip()
        )
        # 0 = success with work; 10 = success with no changes (caller convention).
        if proc.returncode not in (0, 10):
            mark_task_error(
                task_file, task_id, title, "local",
                f"local_exit_{proc.returncode}",
                output or f"local command exited {proc.returncode}",
                log_file,
            )
            return 1
        result_text = output or "Local command completed with no changes."
        write_log(log_file, task_id, title, "success", "local", result_text, None, None)
        print(result_text, flush=True)
        return 0

    if not router_script.exists():
        print(f"Error: router script not found: {router_script}", file=sys.stderr)
        return 1

    # Build prompt
    body = strip_frontmatter(task_file)
    prompt = build_prompt(task_id, title, body)

    # Call router
    print(f"  Calling router (channel=async-task, mode=direct_only, provider={task_provider or 'priority'}) ...", flush=True)
    try:
        response = call_router(router_script, task_id, prompt, task_provider)
    except subprocess.TimeoutExpired:
        mark_task_error(
            task_file, task_id, title, task_provider,
            "router_timeout", "router call timed out", log_file
        )
        return 1
    except Exception as exc:
        mark_task_error(
            task_file, task_id, title, task_provider,
            "router_exception", str(exc), log_file
        )
        return 1

    provider_used = response.get("provider_used") or task_provider
    status = response.get("status", "failed")
    reply_text = response.get("reply_text", "")
    error_code = response.get("error_code")
    error_text = response.get("error")

    if status != "success" or not reply_text:
        error_msg = error_text or f"router returned status={status}"
        mark_task_error(
            task_file, task_id, title, provider_used,
            error_code or "router_failed", error_msg, log_file
        )
        return 1

    # Success: write log
    write_log(log_file, task_id, title, "success", provider_used, reply_text, None, None)
    print(f"  → provider_used: {provider_used}", flush=True)
    # Output reply_text to stdout for execute_active.sh to capture if needed
    print(reply_text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
