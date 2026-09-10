"""State-home contracts: runtime root, planet buckets, canonical identity.

Every test writes only inside tmp_path via SOLAR_APP_DATA. Nothing here may
touch the live store.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "solar-client" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import solar_runtime  # noqa: E402


@pytest.fixture()
def app_data(tmp_path, monkeypatch):
    base = tmp_path / "AppData"
    base.mkdir()
    monkeypatch.setenv("SOLAR_APP_DATA", str(base))
    monkeypatch.delenv("SOLAR_RUNTIME_ROOT", raising=False)
    importlib.reload(solar_runtime)
    return base


def test_runtime_root_is_outside_the_workspace(app_data):
    root = solar_runtime.runtime_root()
    assert root == (app_data / "Solar" / "runtime").resolve()
    assert "sun/runtime" not in str(root)


def test_runtime_root_honours_explicit_override(app_data, tmp_path, monkeypatch):
    target = tmp_path / "explicit"
    target.mkdir()
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(target))
    assert solar_runtime.runtime_root() == target.resolve()


def test_runtime_dir_composes_and_creates_on_request(app_data):
    path = solar_runtime.runtime_dir("async-tasks", "queued", create=True)
    assert path.is_dir()
    assert path == solar_runtime.runtime_root() / "async-tasks" / "queued"


def test_symlinked_and_real_workspace_are_one_identity(app_data, tmp_path):
    real = tmp_path / "real" / "planets" / "louis"
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")

    via_real = solar_runtime.planet_state_dir(real, "calendar-sync")
    via_link = solar_runtime.planet_state_dir(link / "planets" / "louis", "calendar-sync")

    assert via_real == via_link
    assert solar_runtime.planet_key(real) == solar_runtime.planet_key(link / "planets" / "louis")

    index = json.loads(solar_runtime.planets_index_path().read_text(encoding="utf-8"))
    assert len(index["planets"]) == 1


def test_same_name_different_planets_get_different_buckets(app_data, tmp_path):
    one = tmp_path / "ws-a" / "planets" / "louis"
    two = tmp_path / "ws-b" / "planets" / "louis"
    one.mkdir(parents=True)
    two.mkdir(parents=True)

    bucket_one = solar_runtime.planet_bucket(one)
    bucket_two = solar_runtime.planet_bucket(two)

    assert bucket_one == "louis"
    assert bucket_two != bucket_one
    assert bucket_two.startswith("louis-")
    assert len(bucket_two) == len("louis-") + 12


def test_bucket_assignment_is_stable_across_calls(app_data, tmp_path):
    planet = tmp_path / "ws" / "planets" / "louis"
    planet.mkdir(parents=True)
    first = solar_runtime.planet_bucket(planet)
    second = solar_runtime.planet_bucket(planet)
    assert first == second


def test_planet_state_dir_is_never_inside_the_repo(app_data, tmp_path):
    planet = tmp_path / "ws" / "planets" / "louis"
    planet.mkdir(parents=True)
    state = solar_runtime.planet_state_dir(planet, "calendar-sync", create=True)
    assert state.is_dir()
    assert not str(state).startswith(str(tmp_path / "ws"))
    assert state == app_data.resolve() / "Solar" / "planets" / "louis" / "calendar-sync"


def test_index_is_written_atomically_and_holds_no_secrets(app_data, tmp_path):
    planet = tmp_path / "ws" / "planets" / "louis"
    planet.mkdir(parents=True)
    solar_runtime.planet_bucket(planet)
    index_path = solar_runtime.planets_index_path()
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["version"] == solar_runtime.INDEX_VERSION
    entry = next(iter(data["planets"].values()))
    assert set(entry) == {"path", "name", "bucket"}
    assert not list(index_path.parent.glob(".index-*"))


def test_no_string_literal_composes_sun_runtime(app_data):
    """Prose may mention it; no *value* may be it."""
    import ast

    tree = ast.parse((SCRIPTS / "solar_runtime.py").read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "sun/runtime" in node.value
        and node.value not in docstrings
    ]
    assert offenders == [], offenders


def test_resolved_homes_never_land_inside_a_workspace(app_data, tmp_path):
    planet = tmp_path / "ws" / "planets" / "louis"
    planet.mkdir(parents=True)
    for path in (
        solar_runtime.runtime_root(),
        solar_runtime.runtime_dir("async-tasks"),
        solar_runtime.runtime_dir("delegations"),
        solar_runtime.planet_state_dir(planet, "calendar-sync"),
    ):
        assert "/sun/" not in str(path)
        assert not str(path).startswith(str(tmp_path / "ws"))
