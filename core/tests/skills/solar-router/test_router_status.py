"""status_router.sh: the Providers block follows the configured priority, and a run whose task
is over is not reported as in flight."""
from __future__ import annotations

import os
import uuid
import subprocess
from pathlib import Path

import pytest

import solar_state
from router_open_runs import open_runs

SCRIPT = Path(__file__).resolve().parents[3] / "skills" / "solar-router" / "scripts" / "status_router.sh"


def _start(rid, **extra):
    return {"event": "start", "router_id": rid, "ts": "2026-10-28T16:55:34+00:00", **extra}


def test_open_runs_skips_terminal_tasks_and_closed_runs():
    statuses = {"task_a": "cancelled", "task_b": "active", "gen-c": "completed"}
    rows = [
        _start("r-cancelled", task_id="task_a"),
        _start("r-active", task_id="task_b"),
        _start("r-by-request", request_id="task_gen-c"),
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
    for name in ("codex", "claude", "agy", "agent"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", SOLAR_WORKSPACE=str(ws))
    for key in ("SOLAR_ROUTER_PROVIDER_PRIORITY", "SOLAR_AI_PROVIDER_PRIORITY"):
        env.pop(key, None)
    env["_STUB_BIN"] = str(bin_dir)
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


def test_failing_provider_is_listed_without_script_missing_note(status_env):
    os.remove(Path(status_env["_STUB_BIN"]) / "claude")
    status_env["PATH"] = status_env["_STUB_BIN"] + ":/usr/bin:/bin"
    status_env["SOLAR_ROUTER_PROVIDER_PRIORITY"] = "codex,claude"
    proc = _run_status(status_env)
    block = _providers_block(proc.stdout)
    assert "- claude: FAIL" in block and "- codex: OK" in block, proc.stdout
    assert "not available" not in proc.stdout


def _make_task(task_id, final):
    """A real task in the store, driven to `final` through allowed transitions."""
    with solar_state.session() as store:
        store.task_create([("title", f'"{task_id}"')], "body", status="queued", task_id=task_id)
        if final == "cancelled":
            store.task_cancel(task_id)
        else:
            with solar_state._transaction(store.conn) as conn:
                conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (final, task_id))


@pytest.mark.parametrize("final", sorted(solar_state.TERMINAL_STATUSES))
@pytest.mark.parametrize("ts", ["2026-10-28T16:55:34Z", "2026-10-28T16:55:34+00:00", "2026-10-28T16:55:34"])
def test_terminal_task_run_is_not_in_flight(status_env, final, ts):
    task_id = str(uuid.uuid4())
    _make_task(task_id, final)
    with solar_state.session() as store:
        # The executor's real request id: task_ + the id task_create() generated; no task_id field.
        store.audit_append(_start("dead0000-aaaa", request_id=f"task_{task_id}", ts=ts, user_id="solar-async-tasks"))
        store.audit_append(_start("live0000-bbbb", request_id="telegram-1", ts=ts))
    out = _run_status(status_env).stdout
    in_flight = out.split("In-flight:")[1].split("Last ")[0]
    assert "dead0000" not in in_flight
    assert "live0000" in in_flight and "started unknown" not in in_flight
    last = out.split("Last ")[1]
    assert any("dead0000" in l and "(interrupted)" in l for l in last.splitlines()), last
    assert any("live0000" in l and "(in-flight)" in l for l in last.splitlines()), last
    assert _run_status(status_env, "--stale-count-all").stdout.strip() == "1"
    assert _run_status(status_env, "--stale-count", "--max-age-hours", "100000").stdout.strip() == "1"


def test_no_deprecation_warning_even_when_promoted_to_error(status_env):
    with solar_state.session() as store:
        store.audit_append(_start("live0000-bbbb", request_id="telegram-1"))
    status_env["PYTHONWARNINGS"] = "error::DeprecationWarning"
    proc = _run_status(status_env)
    assert proc.returncode == 0 and "Traceback" not in proc.stderr, proc.stderr
