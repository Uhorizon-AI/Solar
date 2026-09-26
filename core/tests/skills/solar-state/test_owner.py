"""One runtime, one workspace. The path is not the identity."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import solar_state
from solar_state import StateUnavailable, claim_owner, session


def _settings(workspace: Path, workspace_id: str | None) -> None:
    solar = workspace / ".solar"
    solar.mkdir(parents=True, exist_ok=True)
    (workspace / "sun").mkdir(parents=True, exist_ok=True)
    data = {"layout": "solar-client-v1.2"}
    if workspace_id:
        data["workspace_id"] = workspace_id
    (solar / "settings.json").write_text(json.dumps(data) + "\n", encoding="utf-8")


def _use(monkeypatch, runtime: Path, workspace: Path) -> None:
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    monkeypatch.setenv("SOLAR_WORKSPACE", str(workspace))


def test_claim_creates_once_and_session_refuses_until_then(tmp_path, monkeypatch):
    runtime, workspace = tmp_path / "runtime", tmp_path / "workspace"
    runtime.mkdir()
    _settings(workspace, "pending-id")
    _use(monkeypatch, runtime, workspace)
    with pytest.raises(StateUnavailable, match="no workspace owner"):
        with session(runtime):
            pass
    first = claim_owner(workspace, root=runtime)
    second = claim_owner(workspace, first["workspace_id"], root=runtime)
    assert first["action"] == "created"
    assert second["action"] == "unchanged"
    assert second["workspace_id"] == first["workspace_id"]
    _settings(workspace, first["workspace_id"])
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    with session(runtime) as store:
        assert store.counts()["tasks"] == {}


def test_claim_does_not_open_settings(tmp_path, monkeypatch):
    runtime, workspace = tmp_path / "runtime", tmp_path / "workspace"
    runtime.mkdir()
    _settings(workspace, None)
    settings = workspace / ".solar" / "settings.json"
    before = settings.read_bytes()
    opened: list[str] = []
    real_open = open

    def tracking(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking)
    claim_owner(workspace, root=runtime)
    assert not any(path.endswith("settings.json") for path in opened)
    assert settings.read_bytes() == before


def test_resume_after_a_crash_between_the_two_writes(tmp_path, monkeypatch):
    runtime, workspace = tmp_path / "runtime", tmp_path / "workspace"
    runtime.mkdir()
    _settings(workspace, None)
    _use(monkeypatch, runtime, workspace)
    created = claim_owner(workspace, root=runtime)
    settings = workspace / ".solar" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data.pop("workspace_id", None)
    settings.write_text(json.dumps(data) + "\n", encoding="utf-8")
    again = claim_owner(workspace, root=runtime)
    assert again["workspace_id"] == created["workspace_id"]
    assert again["action"] == "unchanged"
    assert "workspace_id" not in json.loads(settings.read_text(encoding="utf-8"))

    (runtime / "workspace-owner.json").unlink()
    _settings(workspace, created["workspace_id"])
    adopted = claim_owner(workspace, created["workspace_id"], root=runtime)
    assert adopted["action"] == "created"
    assert adopted["workspace_id"] == created["workspace_id"]
    with pytest.raises(StateUnavailable, match="no workspace owner"):
        (runtime / "workspace-owner.json").unlink()
        with session(runtime):
            pass


def test_symlink_and_realpath_are_the_same_place(tmp_path):
    runtime = tmp_path / "runtime"
    workspace = tmp_path / "workspace"
    runtime.mkdir()
    _settings(workspace, "same-id")
    link = tmp_path / "link"
    link.symlink_to(workspace, target_is_directory=True)
    claim_owner(link, "same-id", root=runtime)
    again = claim_owner(workspace, "same-id", root=runtime)
    assert again["action"] == "unchanged"


def test_a_move_rebinds_and_a_copy_does_not(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    original = tmp_path / "original"
    runtime.mkdir()
    _settings(original, "moved-id")
    claim_owner(original, "moved-id", root=runtime)
    moved = tmp_path / "moved"
    original.rename(moved)
    rebound = claim_owner(moved, "moved-id", root=runtime)
    assert rebound["action"] == "rebound"
    _use(monkeypatch, runtime, moved)
    _settings(moved, "moved-id")
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    with session(runtime):
        pass

    home = tmp_path / "home"
    copy = tmp_path / "copy"
    runtime2 = tmp_path / "runtime2"
    runtime2.mkdir()
    _settings(home, "copied-id")
    _settings(copy, "copied-id")
    claim_owner(home, "copied-id", root=runtime2)
    with pytest.raises(StateUnavailable, match="copy"):
        claim_owner(copy, "copied-id", root=runtime2)
    rebound = claim_owner(copy, "copied-id", rebind=True, root=runtime2)
    assert rebound["action"] == "rebound"
    assert "home" in rebound["previous_path"]


def test_a_different_id_is_refused_even_with_rebind(tmp_path):
    runtime, workspace, other = tmp_path / "runtime", tmp_path / "workspace", tmp_path / "other"
    runtime.mkdir()
    _settings(workspace, "owner-id")
    _settings(other, "other-id")
    claim_owner(workspace, "owner-id", root=runtime)
    with pytest.raises(StateUnavailable, match="owner-id"):
        claim_owner(other, "other-id", rebind=True, root=runtime)


def test_session_reads_the_env_and_sees_the_next_change(tmp_path, monkeypatch):
    runtime, workspace = tmp_path / "runtime", tmp_path / "workspace"
    runtime.mkdir()
    _settings(workspace, "live-id")
    claim_owner(workspace, "live-id", root=runtime)
    _use(monkeypatch, runtime, workspace)
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    with session(runtime):
        pass
    other = tmp_path / "other"
    _settings(other, "someone-else")
    monkeypatch.setenv("SOLAR_WORKSPACE", str(other))
    with pytest.raises(StateUnavailable, match="live-id"):
        with session(runtime):
            pass
    monkeypatch.setenv("SOLAR_WORKSPACE", str(workspace))
    settings = workspace / ".solar" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["workspace_id"] = "replaced-id"
    settings.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(StateUnavailable, match="live-id"):
        with session(runtime):
            pass
    info = solar_state.describe(runtime)
    assert info["ready"] is False and "live-id" in info["reason"]


def test_repair_keep_chooses_a_side_and_bare_repair_writes_nothing(tmp_path, monkeypatch):
    runtime, workspace = tmp_path / "runtime", tmp_path / "workspace"
    runtime.mkdir()
    _settings(workspace, "settings-id")
    (workspace / "sun").mkdir(exist_ok=True)
    claim_owner(workspace, "owner-id", root=runtime)
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    monkeypatch.delenv("SOLAR_WORKSPACE", raising=False)
    script = Path(solar_state.__file__).resolve().parents[2] / "solar-client" / "scripts" / "client_claim_runtime.sh"
    env = os.environ.copy()
    env["SOLAR_RUNTIME_ROOT"] = str(runtime)
    env["SOLAR_WORKSPACE"] = str(workspace)
    env["SOLAR_ROOT"] = str(Path(solar_state.__file__).resolve().parents[4])

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(script), *args], cwd=workspace, env=env, text=True, capture_output=True)

    bare = run("--repair")
    assert bare.returncode != 0
    assert "owner-id" in bare.stdout and "settings-id" in bare.stdout
    stored = json.loads((runtime / "workspace-owner.json").read_text(encoding="utf-8"))
    assert stored["workspace_id"] == "owner-id"
    assert json.loads((workspace / ".solar" / "settings.json").read_text())["workspace_id"] == "settings-id"

    kept_owner = run("--repair", "--keep", "owner")
    assert kept_owner.returncode == 0, kept_owner.stderr
    assert json.loads((workspace / ".solar" / "settings.json").read_text())["workspace_id"] == "owner-id"

    (workspace / ".solar" / "settings.json").write_text(
        json.dumps({"layout": "solar-client-v1.2", "workspace_id": "settings-id"}) + "\n",
        encoding="utf-8")
    kept_settings = run("--repair", "--keep", "settings")
    assert kept_settings.returncode == 0, kept_settings.stderr
    stored = json.loads((runtime / "workspace-owner.json").read_text(encoding="utf-8"))
    assert stored["workspace_id"] == "settings-id"

    owner_before = (runtime / "workspace-owner.json").read_text(encoding="utf-8")
    settings_before = (workspace / ".solar" / "settings.json").read_text(encoding="utf-8")
    missing_value = run("--keep")
    assert missing_value.returncode == 2
    assert "Usage" in missing_value.stderr
    keep_without_repair = run("--keep", "owner")
    assert keep_without_repair.returncode == 2
    assert "Usage" in keep_without_repair.stderr
    assert (runtime / "workspace-owner.json").read_text(encoding="utf-8") == owner_before
    assert (workspace / ".solar" / "settings.json").read_text(encoding="utf-8") == settings_before
