from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "core" / "skills" / "solar-async-tasks" / "scripts"


def write_task(
    task_root: Path,
    state: str,
    slug: str,
    task_id: str,
    *,
    priority: str = "normal",
    extra_meta: str = "",
) -> Path:
    task_dir = task_root / state
    task_dir.mkdir(parents=True, exist_ok=True)
    task_file = task_dir / f"{slug}.md"
    frontmatter = (
        "---\n"
        f'id: "{task_id}"\n'
        f'title: "{slug}"\n'
        'created: "2026-04-06T09:00:00+02:00"\n'
        f'status: {state if state != "archive" else "archived"}\n'
        f'priority: {priority}\n'
        "recurring: false\n"
        f"{extra_meta}"
        "---\n\n"
        f"# {slug}\n"
    )
    task_file.write_text(frontmatter, encoding="utf-8")
    return task_file


def run_script(script_name: str, task_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SOLAR_TASK_ROOT"] = str(task_root)
    return subprocess.run(
        ["bash", str(SCRIPTS_DIR / script_name), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_await_subtasks_requeues_parent_with_unique_child_ids(tmp_path: Path) -> None:
    task_root = tmp_path / "async-tasks"
    parent_id = "parent-1"
    write_task(task_root, "active", "parent-task", parent_id)

    result = run_script("await_subtasks.sh", task_root, parent_id, "child-1", "child-2", "child-1")

    assert result.returncode == 0, result.stderr
    parent_file = task_root / "queued" / "parent-task.md"
    assert parent_file.exists()
    content = parent_file.read_text(encoding="utf-8")
    assert "status: queued" in content
    assert 'blocked_by_task_ids: "child-1,child-2"' in content


def test_start_next_skips_blocked_parent_until_dependencies_complete(tmp_path: Path) -> None:
    task_root = tmp_path / "async-tasks"
    write_task(
        task_root,
        "queued",
        "parent-task",
        "parent-1",
        priority="high",
        extra_meta='blocked_by_task_ids: "child-1"\n',
    )
    write_task(task_root, "queued", "child-task", "child-1", priority="low")

    result = run_script("start_next.sh", task_root)

    assert result.returncode == 0, result.stderr
    assert (task_root / "active" / "child-task.md").exists()
    assert (task_root / "queued" / "parent-task.md").exists()
    assert "Skipping blocked task" in result.stdout


def test_start_next_unblocks_parent_when_dependencies_are_done(tmp_path: Path) -> None:
    task_root = tmp_path / "async-tasks"
    write_task(
        task_root,
        "queued",
        "parent-task",
        "parent-1",
        extra_meta='blocked_by_task_ids: "child-1"\n',
    )
    write_task(task_root, "completed", "child-task", "child-1")

    result = run_script("start_next.sh", task_root)

    assert result.returncode == 0, result.stderr
    parent_file = task_root / "active" / "parent-task.md"
    assert parent_file.exists()
    content = parent_file.read_text(encoding="utf-8")
    assert "status: active" in content
    assert "blocked_by_task_ids:" not in content


def test_await_subtasks_preserves_detach_opt_out_field(tmp_path: Path) -> None:
    task_root = tmp_path / "async-tasks"
    parent_id = "parent-1"
    write_task(task_root, "active", "parent-task", parent_id, extra_meta="detach_subtasks: true\n")

    result = run_script("await_subtasks.sh", task_root, parent_id, "child-1")

    assert result.returncode == 0, result.stderr
    parent_file = task_root / "queued" / "parent-task.md"
    content = parent_file.read_text(encoding="utf-8")
    assert "detach_subtasks: true" in content
    assert 'blocked_by_task_ids: "child-1"' in content
