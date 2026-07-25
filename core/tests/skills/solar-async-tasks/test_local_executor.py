"""Tests for executor: local in execute_active.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# core/tests/skills/solar-async-tasks/ → parents[3] = core/
CORE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = CORE_ROOT / "skills" / "solar-async-tasks" / "scripts"
EXECUTE = SCRIPTS / "execute_active.py"
sys.path.insert(0, str(SCRIPTS))

import execute_active as ea  # noqa: E402


def _workspace_with_script(tmp_path: Path, body: str = "#!/bin/bash\nexit 0\n") -> tuple[Path, Path]:
    script = tmp_path / "planets" / "louis" / "skills" / "calendar-sync" / "scripts" / "ok.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return tmp_path, script


def _write_task(
    task_root: Path,
    *,
    local_command: str,
    local_timeout: str = "300",
    task_id: str = "local-1",
) -> Path:
    active = task_root / "active"
    active.mkdir(parents=True, exist_ok=True)
    (task_root / "logs").mkdir(parents=True, exist_ok=True)
    path = active / "local-task.md"
    path.write_text(
        "---\n"
        f'id: "{task_id}"\n'
        'title: "Local Task"\n'
        "status: active\n"
        "executor: local\n"
        f"local_command: {local_command}\n"
        f"local_timeout: {local_timeout}\n"
        "---\n\n# Local Task\n",
        encoding="utf-8",
    )
    return path


def _run_executor(task_file: Path, workspace: Path, task_id: str = "local-1") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SOLAR_WORKSPACE"] = str(workspace)
    return subprocess.run(
        [sys.executable, str(EXECUTE), str(task_file), "/nonexistent/router.py", task_id, "Local Task"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_parse_local_timeout_ok():
    assert ea.parse_local_timeout("300") == (300, None)
    assert ea.parse_local_timeout("") == (300, None)


def test_parse_local_timeout_invalid():
    assert ea.parse_local_timeout("abc")[1] == "local_timeout_invalid"
    assert ea.parse_local_timeout("0")[1] == "local_timeout_invalid"
    assert ea.parse_local_timeout("-1")[1] == "local_timeout_invalid"


def test_authorize_rejects_outside_scripts(tmp_path: Path):
    workspace, _ = _workspace_with_script(tmp_path)
    evil = workspace / "tmp" / "evil.sh"
    evil.parent.mkdir(parents=True)
    evil.write_text("#!/bin/bash\nexit 0\n")
    evil.chmod(0o755)
    argv, err = ea.authorize_local_argv(f"bash {evil}", workspace)
    assert argv is None
    assert err == "local_command_unauthorized"


def test_authorize_rejects_operations_scripts(tmp_path: Path):
    workspace, _ = _workspace_with_script(tmp_path)
    evil = workspace / "planets" / "louis" / "operations" / "scripts" / "evil.sh"
    evil.parent.mkdir(parents=True)
    evil.write_text("#!/bin/bash\nexit 0\n")
    evil.chmod(0o755)
    rel = evil.relative_to(workspace).as_posix()
    argv, err = ea.authorize_local_argv(f"bash {rel}", workspace)
    assert argv is None
    assert err == "local_command_unauthorized"


def test_authorize_accepts_planet_script(tmp_path: Path):
    workspace, script = _workspace_with_script(tmp_path)
    rel = script.relative_to(workspace).as_posix()
    argv, err = ea.authorize_local_argv(f"bash {rel}", workspace)
    assert err is None
    assert argv is not None
    assert argv[0] == "bash"
    assert Path(argv[1]) == script.resolve()


def test_local_exit_0_success(tmp_path: Path):
    workspace, script = _workspace_with_script(tmp_path, "#!/bin/bash\necho ok\nexit 0\n")
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    rel = script.relative_to(workspace).as_posix()
    task = _write_task(task_root, local_command=f"bash {rel}")
    proc = _run_executor(task, workspace)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok" in proc.stdout
    assert task.exists()


def test_local_exit_10_success(tmp_path: Path):
    workspace, script = _workspace_with_script(tmp_path, "#!/bin/bash\nexit 10\n")
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    rel = script.relative_to(workspace).as_posix()
    task = _write_task(task_root, local_command=f"bash {rel}")
    proc = _run_executor(task, workspace)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_local_exit_error_moves_to_error(tmp_path: Path):
    workspace, script = _workspace_with_script(tmp_path, "#!/bin/bash\necho boom >&2\nexit 3\n")
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    rel = script.relative_to(workspace).as_posix()
    task = _write_task(task_root, local_command=f"bash {rel}")
    proc = _run_executor(task, workspace)
    assert proc.returncode == 1
    assert not task.exists()
    err = task_root / "error" / "local-task.md"
    assert err.exists()
    assert "local_exit_3" in err.read_text(encoding="utf-8")


def test_local_command_missing(tmp_path: Path):
    workspace = tmp_path
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    active = task_root / "active"
    active.mkdir(parents=True)
    (task_root / "logs").mkdir(parents=True)
    task = active / "local-task.md"
    task.write_text(
        "---\nid: \"local-1\"\ntitle: \"Local Task\"\nstatus: active\n"
        "executor: local\nlocal_timeout: 30\n---\n\n# x\n",
        encoding="utf-8",
    )
    proc = _run_executor(task, workspace)
    assert proc.returncode == 1
    err = task_root / "error" / "local-task.md"
    assert err.exists()
    assert "local_command_missing" in err.read_text(encoding="utf-8")


def test_local_timeout_invalid_fail_closed(tmp_path: Path):
    workspace, script = _workspace_with_script(tmp_path)
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    rel = script.relative_to(workspace).as_posix()
    task = _write_task(task_root, local_command=f"bash {rel}", local_timeout="not-a-number")
    proc = _run_executor(task, workspace)
    assert proc.returncode == 1
    err = task_root / "error" / "local-task.md"
    assert err.exists()
    body = err.read_text(encoding="utf-8")
    assert "local_timeout_invalid" in body
    assert "status: error" in body


def test_local_timeout_expires(tmp_path: Path):
    workspace, script = _workspace_with_script(tmp_path, "#!/bin/bash\nsleep 5\nexit 0\n")
    task_root = tmp_path / "sun" / "runtime" / "async-tasks"
    rel = script.relative_to(workspace).as_posix()
    task = _write_task(task_root, local_command=f"bash {rel}", local_timeout="1")
    proc = _run_executor(task, workspace)
    assert proc.returncode == 1
    err = task_root / "error" / "local-task.md"
    assert err.exists()
    assert "local_timeout" in err.read_text(encoding="utf-8")
