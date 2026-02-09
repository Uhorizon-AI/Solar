#!/usr/bin/env python3
import json
import os
import shlex
import shutil
import subprocess
import sys
from typing import Dict, List


SUPPORTED_PROVIDERS = {"codex", "claude", "gemini"}

DEFAULT_CMDS: Dict[str, str] = {
    "codex": "codex exec --skip-git-repo-check --full-auto --",
    "claude": "claude -p --permission-mode bypassPermissions",
    "gemini": "gemini -y",
}


def get_cmd(provider: str) -> List[str]:
    env_key = f"SOLAR_AI_{provider.upper()}_CMD"
    raw = os.getenv(env_key, DEFAULT_CMDS[provider]).strip()
    cmd = shlex.split(raw)
    if not cmd:
        raise RuntimeError(f"{env_key} is empty")
    if shutil.which(cmd[0]) is None:
        raise RuntimeError(
            f"client binary not found: {cmd[0]} (provider={provider}, env={env_key})"
        )
    return cmd


def run_provider(provider: str, prompt: str) -> str:
    timeout_sec = int(os.getenv("SOLAR_AI_PROVIDER_TIMEOUT_SEC", "120"))
    cmd = get_cmd(provider) + [prompt]
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )
    if proc.returncode != 0:
        error = proc.stderr.strip() or proc.stdout.strip() or "provider returned non-zero"
        raise RuntimeError(error)
    output = proc.stdout.strip()
    if not output:
        raise RuntimeError("provider returned empty output")
    return output


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("missing stdin payload")

    payload = json.loads(raw)
    provider = str(payload.get("provider", "")).strip().lower()
    text = str(payload.get("text", "")).strip()

    if provider not in SUPPORTED_PROVIDERS:
        raise SystemExit(f"unsupported provider: {provider}")
    if not text:
        raise SystemExit("missing text")

    reply = run_provider(provider, text)
    print(reply)


if __name__ == "__main__":
    main()
