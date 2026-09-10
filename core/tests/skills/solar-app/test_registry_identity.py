"""workspaces.json: one identity per physical path, and the file is not rewritten."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import host_registry  # noqa: E402


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    base = tmp_path / "AppData"
    (base / "Solar").mkdir(parents=True)
    monkeypatch.setenv("SOLAR_APP_DATA", str(base))
    importlib.reload(host_registry)
    return base / "Solar" / "workspaces.json"


def test_stable_hash_agrees_between_symlink_and_real_path(registry, tmp_path):
    real = tmp_path / "Solar"
    real.mkdir()
    link = tmp_path / "SolarLink"
    link.symlink_to(real)
    assert host_registry.stable_hash(str(link)) == host_registry.stable_hash(str(real))
    assert host_registry.gateway_port(str(link)) == host_registry.gateway_port(str(real))


def test_duplicate_entries_collapse_and_oldest_label_wins(registry, tmp_path):
    real = tmp_path / "Solar"
    real.mkdir()
    link = tmp_path / "SolarLink"
    link.symlink_to(real)
    payload = {
        "version": 1,
        "active_path": str(link),
        "workspaces": [
            {"path": str(real), "label": "original", "added_at": "2026-01-01T00:00:00+00:00"},
            {"path": str(link), "label": "duplicate", "added_at": "2026-06-01T00:00:00+00:00"},
        ],
    }
    raw = json.dumps(payload, indent=2) + "\n"
    registry.write_text(raw, encoding="utf-8")

    data = host_registry.load_registry()

    assert len(data["workspaces"]) == 1
    assert data["workspaces"][0]["label"] == "original"
    assert data["workspaces"][0]["path"] == str(real.resolve())
    assert data["active_path"] == str(real.resolve())
    # Reading must not rewrite the file.
    assert registry.read_text(encoding="utf-8") == raw


def test_reading_never_writes_even_with_duplicates(registry, tmp_path):
    """The canonical view is in memory only.

    Only explicit add/remove/use may persist it. During the store move the file
    has to stay byte for byte, so a plain read must not rewrite it.
    """
    real = tmp_path / "Solar"
    real.mkdir()
    link = tmp_path / "SolarLink"
    link.symlink_to(real)
    raw = json.dumps(
        {
            "version": 1,
            "active_path": str(link),
            "workspaces": [
                {"path": str(real), "label": "original", "added_at": "2026-01-01T00:00:00+00:00"},
                {"path": str(link), "label": "duplicate", "added_at": "2026-06-01T00:00:00+00:00"},
            ],
        },
        indent=2,
    ) + "\n"
    registry.write_text(raw, encoding="utf-8")
    before = registry.stat().st_mtime_ns

    for _ in range(3):
        data = host_registry.load_registry()
        host_registry.list_workspaces(data)
        host_registry.get_active_path(data)

    assert registry.read_text(encoding="utf-8") == raw
    assert registry.stat().st_mtime_ns == before


def test_explicit_add_persists_the_canonical_form(registry, tmp_path):
    """The other side of the boundary: add/remove/use may write, and when they
    do they write canonical paths and leave no duplicates behind."""
    real = tmp_path / "Solar"
    real.mkdir()
    link = tmp_path / "SolarLink"
    link.symlink_to(real)
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "active_path": str(real),
                "workspaces": [
                    {"path": str(real), "label": "original", "added_at": "2026-01-01T00:00:00+00:00"}
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    host_registry.add_workspace(str(link), label="via-symlink")

    on_disk = json.loads(registry.read_text(encoding="utf-8"))
    paths = [w["path"] for w in on_disk["workspaces"]]
    assert paths == [str(real.resolve())]
    assert on_disk["workspaces"][0]["label"] == "via-symlink"


def test_already_canonical_registry_is_returned_unchanged(registry, tmp_path):
    real = tmp_path / "Solar"
    real.mkdir()
    payload = {
        "version": 1,
        "active_path": str(real),
        "workspaces": [
            {"path": str(real), "label": "Solar", "added_at": "2026-01-01T00:00:00+00:00"}
        ],
    }
    raw = json.dumps(payload, indent=2) + "\n"
    registry.write_text(raw, encoding="utf-8")

    data = host_registry.load_registry()

    assert data["workspaces"] == payload["workspaces"]
    assert data["active_path"] == payload["active_path"]
    assert registry.read_text(encoding="utf-8") == raw
