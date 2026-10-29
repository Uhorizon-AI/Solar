"""status_router.sh: the Providers block follows the configured priority, and a run whose task
is over is not reported as in flight."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import solar_state
from router_open_runs import open_runs

SCRIPT = Path(__file__).resolve().parents[3] / "skills" / "solar-router" / "scripts" / "status_router.sh"


def _start(rid, **extra):
    return {"event": "start", "router_id": rid, "ts": "2026-10-28T16:55:34+00:00", **extra}


def test_open_runs_skips_terminal_tasks_and_closed_runs():
    statuses = {"task_a": "cancelled", "task_b": "active", "task_c": "completed"}
    rows = [
        _start("r-cancelled", task_id="task_a"),
        _start("r-active", task_id="task_b"),
        _start("r-by-request", request_id="task_c"),
        _start("r-unknown-task", task_id="task_gone"),
        _start("r-no-task", request_id="telegram-1"),
        _start("r-ended", task_id="task_b"),
        {"event": "end", "router_id": "r-ended"},
    ]
    result = open_runs(rows, statuses.get)
    assert set(result) == {"r-active", "r-unknown-task", "r-no-task"}


@pytest.fixture
def status_env(isolated_runtime, tmp_path, monkeypatch):
    ws = isolated_runtime.workspace
    (ws / "AGENTS.md").write_text("# test\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "agent"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", SOLAR_WORKSPACE=str(ws))
    for key in ("SOLAR_ROUTER_PROVIDER_PRIORITY", "SOLAR_AI_PROVIDER_PRIORITY"):
        env.pop(key, None)
    return env


def _run_status(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def _providers_block(out: str) -> list[str]:
    block = out.split("Providers:")[1].split("In-flight:")[0]
    return [line.strip() for line in block.splitlines() if line.strip()]


def test_providers_block_lists_every_configured_provider(status_env):
    status_env["SOLAR_ROUTER_PROVIDER_PRIORITY"] = "codex,claude,agy,agent"
    proc = _run_status(status_env)
    names = [line.split(":")[0].lstrip("- ") for line in _providers_block(proc.stdout)]
    assert names == ["codex", "claude", "agy", "agent"], proc.stdout + proc.stderr
    assert "- agent: OK" in proc.stdout


def test_providers_block_follows_priority_override(status_env):
    status_env["SOLAR_ROUTER_PROVIDER_PRIORITY"] = "agent, codex"
    proc = _run_status(status_env)
    names = [line.split(":")[0].lstrip("- ") for line in _providers_block(proc.stdout)]
    assert names == ["agent", "codex"], proc.stdout + proc.stderr


def test_cancelled_task_run_is_not_in_flight_and_no_deprecation_warning(status_env, isolated_runtime):
    with solar_state.session() as store:
        store.task_create([("title", '"x"')], "body", status="draft", task_id="task_cancelled")
        store.task_create([("title", '"y"')], "body", status="queued", task_id="task_queued")
        store.task_cancel("task_queued")
        store.audit_append(_start("2448d7d9-aaaa", task_id="task_queued"))
        store.audit_append(_start("19e02d89-bbbb", request_id="telegram-1"))
    proc = _run_status(status_env)
    in_flight = proc.stdout.split("In-flight:")[1].split("Last ")[0]
    assert "2448d7d9" not in in_flight
    assert "19e02d89" in in_flight and "started unknown" not in in_flight
    assert "DeprecationWarning" not in proc.stderr
    assert _run_status(status_env, "--stale-count-all").stdout.strip() == "1"
