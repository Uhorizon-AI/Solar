"""The console reads the projection while it is fresh, and says when it is not."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[3]
for _skill in ("solar-app", "solar-paths", "solar-client", "solar-state"):
    _scripts = _CORE / "skills" / _skill / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))


@pytest.fixture
def store(tmp_path, monkeypatch):
    app_data = tmp_path / "app-data"
    workspace = tmp_path / "workspace"
    runtime = app_data / "Solar" / "runtime"
    (runtime / "router").mkdir(parents=True)
    (runtime / "continuity").mkdir(parents=True)
    workspace.mkdir(exist_ok=True)
    monkeypatch.setenv("SOLAR_APP_DATA", str(app_data))
    monkeypatch.delenv("SOLAR_RUNTIME_ROOT", raising=False)

    import solar_state
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format("sqlite")
    with solar_state.session() as store:
        store.task_import(
            '---\nid: "t-one"\ntitle: "One"\ncreated: "2026-09-01T10:00:00+02:00"\n'
            'recurring: true\nrecurring_run_count: 7\nstatus: queued\n---\n\n# One\n',
            status="queued", source_name="one")
        store.task_import(
            '---\nid: "t-two"\ntitle: "Two"\ncreated: "2026-09-02T10:00:00+02:00"\n'
            'status: draft\n---\n\n# Two\n',
            status="draft", source_name="two")
    with solar_state.session() as store:
        for row in (
            {"ts": "2026-09-03T10:00:00+00:00", "event": "start", "router_id": "r1"},
            {"ts": "2026-09-03T10:00:02+00:00", "event": "end", "router_id": "r1",
             "status": "success", "provider": "claude"},
            {"ts": "2026-09-03T11:00:00+00:00", "event": "start", "router_id": "r2"},
            {"ts": "2026-09-03T11:00:02+00:00", "event": "end", "router_id": "r2",
             "status": "error", "provider": "codex"},
        ):
            store.audit_append(row)
        store.continuity_import_text(
            '{"active_task": "fixture", "updated_at": "2026-09-03T11:00:00Z"}\n')

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


def test_the_console_reads_the_state_views(store):
    data = store.index.projection(store.workspace)
    assert data["projection"]["source"] == "state"
    assert data["projection"]["available"] is True
    assert data["projection"]["stale"] == []
    assert data["counts"]["tasks"] == 2
    assert data["counts"]["task_states"]["queued"] == 1
    assert data["counts"]["task_states"]["drafts"] == 1
    assert data["counts"]["recurring"] == 1


def test_the_views_match_the_snapshot(store):
    shown = store.index.projection(store.workspace)
    direct = store.solar.snapshot(store.workspace)
    assert shown["counts"] == direct["counts"]
    assert [row["id"] for row in shown["tasks"]] == [row["id"] for row in direct["tasks"]]
    assert [row["id"] for row in shown["executions"]] == [
        row["id"] for row in direct["executions"]]
    assert shown["health"]["status"] == direct["health"]["status"]
    assert shown["working"] == direct["working"]


def _add_three(store):
    import solar_state
    with solar_state.session() as session:
        session.task_import(
            '---\nid: "t-three"\ntitle: "Three"\ncreated: "2026-09-04T10:00:00+02:00"\n'
            'status: queued\n---\n\n# Three\n',
            status="queued", source_name="three")


def test_a_new_task_is_visible_without_rebuilding_an_index(store):
    store.index.build(store.workspace)
    _add_three(store)
    data = store.index.projection(store.workspace)
    assert data["projection"]["source"] == "state"
    assert data["counts"]["tasks"] == 3


def test_the_side_index_is_not_the_console(store):
    store.index.build(store.workspace)
    _add_three(store)
    data = store.index.projection(store.workspace)
    assert data["projection"]["source"] == "state"
    assert data["counts"]["tasks"] == 3
    assert (store.runtime / "index.sqlite").is_file()
