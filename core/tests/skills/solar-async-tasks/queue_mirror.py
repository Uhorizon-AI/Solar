"""Test-only bridge between a markdown fixture and solar-state.

Production code never writes the queue back to files. Tests that still read a
folder after a script ran get a mirror of the rows, under the same file name
they created.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parents[3]
_STATE = _CORE / "skills" / "solar-state" / "scripts"
if str(_STATE) not in sys.path:
    sys.path.insert(0, str(_STATE))

import solar_state  # noqa: E402

FOLDERS = {
    "draft": "drafts", "planned": "planned", "queued": "queued", "active": "active",
    "completed": "completed", "error": "error", "archived": "archive", "cancelled": "cancelled",
}
FOLDER_STATUS = {folder: status for status, folder in FOLDERS.items()}


def runtime_of(task_root: Path) -> Path:
    if task_root.name == "async-tasks":
        return task_root.parent
    return task_root


def prepare(task_root: Path) -> Path:
    runtime = runtime_of(task_root)
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["SOLAR_RUNTIME_ROOT"] = str(runtime)
    marker = solar_state.format_path(runtime)
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == solar_state.FORMAT_SQLITE:
        if solar_state.db_path(runtime).is_file():
            return runtime
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    return runtime


def task_id_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("id:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    raise AssertionError(f"no id in {path}")


def seed(task_root: Path) -> None:
    """Import fixture markdown that is not already a row."""
    prepare(task_root)
    with solar_state.session() as store:
        present = {task["id"] for task in store.task_list()}
        for folder, status in FOLDER_STATUS.items():
            directory = task_root / folder
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                try:
                    task_id = task_id_of(path)
                except AssertionError:
                    continue
                if task_id in present:
                    continue
                store.task_import(text, status=status, source_name=path.stem)
                present.add(task_id)
        plans = task_root / "subtasks"
        if plans.is_dir():
            for path in sorted(plans.glob("*.json")):
                if store.subtask_plan_text(path.stem):
                    continue
                store.subtask_plan_import_text(path.stem, path.read_text(encoding="utf-8"))


def mirror(task_root: Path) -> None:
    """Write each row back into the folder its status names."""
    prepare(task_root)
    with solar_state.session() as store:
        live: set[Path] = set()
        for task in store.task_list():
            folder = FOLDERS[task["status"]]
            directory = task_root / folder
            directory.mkdir(parents=True, exist_ok=True)
            name = task.get("source_name") or task["id"]
            dest = directory / f"{name}.md"
            dest.write_text(store.task_export(task["id"]), encoding="utf-8")
            live.add(dest.resolve())
    for folder in FOLDERS.values():
        directory = task_root / folder
        if not directory.is_dir():
            continue
        for path in directory.glob("*.md"):
            if path.resolve() not in live:
                path.unlink()


def env_for(task_root: Path, base: dict | None = None) -> dict:
    runtime = prepare(task_root)
    env = dict(base or os.environ)
    env["SOLAR_RUNTIME_ROOT"] = str(runtime)
    env["SOLAR_TASK_ROOT"] = str(task_root)
    return env
