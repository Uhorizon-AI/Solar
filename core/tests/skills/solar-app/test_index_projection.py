"""The console reads the projection while it is fresh, and says when it is not."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[3]
for _skill in ("solar-app", "solar-client"):
    _scripts = _CORE / "skills" / _skill / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))


@pytest.fixture
def store(tmp_path, monkeypatch):
    app_data = tmp_path / "app-data"
    workspace = tmp_path / "workspace"
    runtime = app_data / "Solar" / "runtime"
    for state in ("drafts", "queued", "completed", "logs"):
        (runtime / "async-tasks" / state).mkdir(parents=True)
    (runtime / "router").mkdir(parents=True)
    (runtime / "continuity").mkdir(parents=True)
    workspace.mkdir(exist_ok=True)
    monkeypatch.setenv("SOLAR_APP_DATA", str(app_data))

    (runtime / "async-tasks" / "queued" / "uno.md").write_text(
        '---\nid: "t-uno"\ntitle: "Uno"\ncreated: "2026-09-01T10:00:00+02:00"\n'
        'recurring: true\nrecurring_run_count: 7\n---\n\n# Uno\n', encoding="utf-8")
    (runtime / "async-tasks" / "drafts" / "dos.md").write_text(
        '---\nid: "t-dos"\ntitle: "Dos"\ncreated: "2026-09-02T10:00:00+02:00"\n---\n\n# Dos\n',
        encoding="utf-8")
    audit = runtime / "router" / "audit.jsonl"
    audit.write_text("\n".join(json.dumps(row) for row in [
        {"ts": "2026-09-03T10:00:00+00:00", "event": "start", "router_id": "r1"},
        {"ts": "2026-09-03T10:00:02+00:00", "event": "end", "router_id": "r1",
         "status": "success", "provider": "claude"},
        {"ts": "2026-09-03T11:00:00+00:00", "event": "start", "router_id": "r2"},
        {"ts": "2026-09-03T11:00:02+00:00", "event": "end", "router_id": "r2",
         "status": "error", "provider": "codex"},
    ]) + "\n", encoding="utf-8")
    (runtime / "continuity" / "active.json").write_text(
        '{"active_task": "fixture", "updated_at": "2026-09-03T11:00:00Z"}', encoding="utf-8")

    import app_solar, app_index, importlib
    importlib.reload(app_solar)
    importlib.reload(app_index)
    return Store(workspace=workspace, runtime=runtime, app_index=app_index, app_solar=app_solar)


class Store:
    def __init__(self, workspace, runtime, app_index, app_solar):
        self.workspace = workspace
        self.runtime = runtime
        self.index = app_index
        self.solar = app_solar


def test_without_an_index_the_console_reads_files_and_says_so(store):
    data = store.index.projection(store.workspace)
    assert data["projection"]["source"] == "files"
    assert data["projection"]["available"] is False
    assert data["counts"]["tasks"] == 2


def test_a_fresh_index_serves_the_same_numbers(store):
    store.index.build(store.workspace)
    from_files = store.solar.snapshot(store.workspace)
    from_index = store.index.projection(store.workspace)

    assert from_index["projection"]["source"] == "index"
    assert from_index["counts"] == from_files["counts"]
    assert [row["id"] for row in from_index["tasks"]] == [row["id"] for row in from_files["tasks"]]
    assert [row["id"] for row in from_index["executions"]] == [
        row["id"] for row in from_files["executions"]]
    assert from_index["health"]["status"] == from_files["health"]["status"]
    assert from_index["working"] == from_files["working"]


def test_a_changed_source_marks_the_projection_stale_and_falls_back(store):
    store.index.build(store.workspace)
    (store.runtime / "async-tasks" / "queued" / "tres.md").write_text(
        '---\nid: "t-tres"\ntitle: "Tres"\ncreated: "2026-09-04T10:00:00+02:00"\n---\n\n# Tres\n',
        encoding="utf-8")

    data = store.index.projection(store.workspace)
    assert data["projection"]["source"] == "files"
    assert data["projection"]["available"] is True
    assert data["projection"]["stale"], "a new task file must invalidate the projection"
    # Falling back means the console is still correct, not merely honest.
    assert data["counts"]["tasks"] == 3


def test_rebuilding_makes_it_fresh_again(store):
    store.index.build(store.workspace)
    (store.runtime / "async-tasks" / "queued" / "tres.md").write_text(
        '---\nid: "t-tres"\ntitle: "Tres"\ncreated: "2026-09-04T10:00:00+02:00"\n---\n\n# Tres\n',
        encoding="utf-8")
    assert store.index.projection(store.workspace)["projection"]["source"] == "files"
    store.index.build(store.workspace)
    data = store.index.projection(store.workspace)
    assert data["projection"]["source"] == "index"
    assert data["counts"]["tasks"] == 3
