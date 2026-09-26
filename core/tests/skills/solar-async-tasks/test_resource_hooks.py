"""Installed resource hooks lock, release, and run on_error."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "solar-async-tasks" / "scripts"
STATE = Path(__file__).resolve().parents[3] / "skills" / "solar-state" / "scripts"
sys.path.insert(0, str(STATE))

import solar_state  # noqa: E402

from queue_mirror import env_for  # noqa: E402


def _queued(title: str) -> str:
    with solar_state.session() as store:
        return store.task_create(
            [
                ("title", json.dumps(title)),
                ("priority", "normal"),
                ("scheduled_time", json.dumps("now")),
                ("recurring", "false"),
                ("cleanup_required", "true"),
                ("resources", "demo"),
            ],
            f"\n# {title}\n",
            status="queued",
        )


def test_installed_hooks_lock_release_and_fail_closed(tmp_path: Path):
    root = tmp_path / "runtime" / "async-tasks"
    env = env_for(root, {**os.environ, "SOLAR_WORKSPACE": str(tmp_path)})

    installed = subprocess.run(
        ["bash", str(SCRIPTS / "install_hooks.sh"), "demo"],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert installed.returncode == 0, installed.stderr
    for name in ("pre_start.sh", "post_complete.sh", "on_error.sh"):
        assert (root / "hooks" / "demo" / name).is_file()

    task_id = _queued("Hold the lock")
    started = subprocess.run(
        ["bash", str(SCRIPTS / "start_next.sh")],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert started.returncode == 0, started.stderr
    lock = root / ".locks" / "demo.lock"
    assert lock.is_file()
    assert lock.read_text(encoding="utf-8").startswith(task_id)

    finished = subprocess.run(
        ["bash", str(SCRIPTS / "complete.sh"), task_id],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert finished.returncode == 0, finished.stderr
    assert not lock.exists()

    (root / "hooks" / "demo" / "post_complete.sh").write_text(
        "#!/bin/bash\nexit 1\n", encoding="utf-8")
    failed_id = _queued("Cleanup fails")
    started = subprocess.run(
        ["bash", str(SCRIPTS / "start_next.sh")],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert started.returncode == 0, started.stderr
    assert lock.is_file()
    failed = subprocess.run(
        ["bash", str(SCRIPTS / "complete.sh"), failed_id],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "Running on_error hook" in failed.stdout
    assert not lock.exists()
    with solar_state.session() as store:
        assert store.task_status(failed_id) == "error"
