"""Opt-in profile, real registered MCP probe, managed publication and rollback."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CORE / "skills/solar-client/scripts"))
import client_profile as cp
from skill_inventory import inventory


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    (ws / "sun").mkdir(parents=True)
    (ws / ".solar").mkdir()
    (ws / ".solar/settings.json").write_text('{"core_source":"global"}')
    folder = ws / "planets/demo/skills/analysis"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: analysis\ndescription: Fixture analysis\n---\nInstructions")
    home = tmp_path / "codex"
    home.mkdir()
    env = dict(SOLAR_ROOT=str(CORE.parent), SOLAR_WORKSPACE=str(ws),
               SOLAR_APP_DATA=str(tmp_path / "app-data"), SOLAR_RUNTIME_ROOT=str(tmp_path / "runtime"))
    config = '[mcp_servers.solar]\ncommand = ' + json.dumps(sys.executable) + '\nargs = [' + json.dumps(str(CORE / "skills/solar-mcp/scripts/mcp_server.py")) + ']\n[mcp_servers.solar.env]\n'
    config += "".join(key + " = " + json.dumps(value) + "\n" for key, value in env.items())
    (home / "config.toml").write_text(config)
    monkeypatch.setenv("CODEX_HOME", str(home))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(ws)
    mock = tmp_path / "launchctl"
    mock.write_text("#!/bin/sh\nexit 1\n")
    mock.chmod(0o755)
    monkeypatch.setenv("SOLAR_CLIENT_LAUNCHCTL", str(mock))
    return ws


def publish(ws):
    # Keep the repository's containment guard on the supported Client path.
    command = 'source "$1"; solar_test_guard; bash "$2" --codex-only'
    return subprocess.run(["bash", "-c", command, "_", str(CORE / "tests/support/shell_runtime_guard.sh"),
                           str(CORE / "skills/solar-client/scripts/client_sync.sh")],
                          cwd=ws, capture_output=True, text=True, timeout=25)


def configure(ws, mode, dry=False):
    args = ["bash", str(CORE / "skills/solar-client/scripts/client_sync.sh"), "profile", "set", mode]
    if mode == "discovery":
        args += ["--codex-only"]
    if dry:
        args += ["--dry-run"]
    return subprocess.run(args, cwd=ws, capture_output=True, text=True, timeout=15)


def test_real_probe_reduced_publication_and_native_rollback(workspace):
    ws = workspace
    first = publish(ws)
    assert first.returncode == 0, first.stderr
    surface = ws / ".agents/skills"
    assert (surface / "demo:analysis/SKILL.md").exists(), first.stdout + first.stderr
    personal = surface / "personal"
    personal.mkdir()
    (personal / "SKILL.md").write_text("Personal resource")
    before = (ws / ".solar/settings.json").read_bytes()
    preview = configure(ws, "discovery", dry=True)
    assert preview.returncode == 0, preview.stderr
    report = json.loads(preview.stdout)
    assert report["initial_count"] == 3
    assert report["initial_catalog_bytes"] < report["full_catalog_bytes"]
    assert (ws / ".solar/settings.json").read_bytes() == before
    assert configure(ws, "discovery").returncode == 0
    reduced = publish(ws)
    assert reduced.returncode == 0, reduced.stderr
    assert not (surface / "demo:analysis").exists()
    assert (personal / "SKILL.md").exists()
    assert (surface / "solar-mcp/SKILL.md").exists()
    assert "demo:analysis" in inventory(ws, CORE)
    assert configure(ws, "native").returncode == 0
    assert publish(ws).returncode == 0
    assert (surface / "demo:analysis/SKILL.md").exists(), first.stdout + first.stderr


def test_missing_mcp_refuses_before_settings_or_surface_change(workspace, monkeypatch):
    ws = workspace
    assert publish(ws).returncode == 0
    before = (ws / ".solar/settings.json").read_bytes()
    Path(os.environ["CODEX_HOME"], "config.toml").unlink()
    assert configure(ws, "discovery").returncode != 0
    assert (ws / ".solar/settings.json").read_bytes() == before
    assert (ws / ".agents/skills/demo:analysis/SKILL.md").exists()
    (ws / ".solar/settings.json").write_text(json.dumps(dict(agents_skill_profile=dict(mode="discovery", clients=["codex"]))))
    assert publish(ws).returncode != 0
    assert (ws / ".agents/skills/demo:analysis/SKILL.md").exists()


def test_essential_exclusion_and_unmanaged_collision_refuse(workspace):
    config = dict(agents_skill_profile=dict(mode="discovery", clients=["codex"]), sync_exclude_skills=["solar-mcp"])
    (workspace / ".solar/settings.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="missing or excluded"):
        cp.selected(workspace, CORE, config)
    (workspace / ".solar/settings.json").write_text("{}")
    path = workspace / ".agents/skills/solar-mcp"
    path.mkdir(parents=True)
    with pytest.raises(ValueError, match="unmanaged"):
        cp.selected(workspace, CORE, dict(agents_skill_profile=dict(mode="discovery", clients=["codex"])))


def test_profile_write_migrates_legacy_and_preserves_unknown_fields(workspace):
    settings = workspace / ".solar/settings.json"
    settings.unlink()
    legacy = workspace / ".solar/manifest.json"
    legacy.write_text('{"custom":"kept", "core_source":"global"}')
    result = configure(workspace, "native")
    assert result.returncode == 0, result.stderr
    saved = json.loads(settings.read_text())
    assert saved["custom"] == "kept"
    assert saved["scope"] == "workspace"
    assert saved["layout"] == "solar-client-v1.2"
    assert not legacy.exists()


def test_workspace_mismatch_refuses_activation(workspace):
    config = Path(os.environ["CODEX_HOME"], "config.toml")
    config.write_text(config.read_text().replace(str(workspace), str(workspace.parent / "another")))
    before = (workspace / ".solar/settings.json").read_bytes()
    assert configure(workspace, "discovery").returncode != 0
    assert (workspace / ".solar/settings.json").read_bytes() == before


def test_canonical_writer_refreshes_identity_and_drops_portable_keys(workspace):
    settings = workspace / ".solar/settings.json"
    settings.write_text(json.dumps(dict(core_source="global", core_commit="stale", client_version="stale", bundle_path="old", bundle_checksum="old", snapshot_at="old", snapshot_outdated=True, custom="kept")))
    assert configure(workspace, "native").returncode == 0
    saved = json.loads(settings.read_text())
    assert saved["core_commit"] != "stale"
    assert saved["client_version"] != "stale"
    assert saved["custom"] == "kept"
    assert not {"bundle_path", "bundle_checksum", "snapshot_at", "snapshot_outdated"} & saved.keys()


def test_writer_failure_is_atomic_and_keeps_legacy(workspace, monkeypatch):
    settings = workspace / ".solar/settings.json"
    before = settings.read_bytes()
    legacy = workspace / ".solar/manifest.json"
    legacy.write_text('{"custom":"legacy"}')
    monkeypatch.setenv("SOLAR_CLIENT_TEST_FAIL_BEFORE_REPLACE", "1")
    assert configure(workspace, "native").returncode != 0
    assert settings.read_bytes() == before
    assert legacy.exists()


def test_discovery_refuses_antigravity_before_pruning(workspace):
    assert publish(workspace).returncode == 0
    command = ["bash", str(CORE / "skills/solar-client/scripts/client_sync.sh"), "profile", "set", "discovery"]
    before = (workspace / ".solar/settings.json").read_bytes()
    denied = subprocess.run(command, cwd=workspace, capture_output=True, text=True)
    assert denied.returncode != 0
    assert "Codex-only" in denied.stderr
    assert (workspace / ".solar/settings.json").read_bytes() == before
    allowed = configure(workspace, "discovery")
    assert allowed.returncode == 0, allowed.stderr
    assert "Antigravity must not use" in allowed.stderr
    args = [sys.executable, str(CORE / "skills/solar-client/scripts/client_profile.py"), "--workspace", str(workspace), "--core", str(CORE), "index", "--include-antigravity"]
    assert subprocess.run(args, capture_output=True).returncode != 0
    command = 'source "$1"; solar_test_guard; bash "$2" --antigravity-only'
    refused = subprocess.run(["bash", "-c", command, "_", str(CORE / "tests/support/shell_runtime_guard.sh"), str(CORE / "skills/solar-client/scripts/client_sync.sh")], cwd=workspace, capture_output=True, text=True)
    assert refused.returncode != 0
    assert (workspace / ".agents/skills/demo:analysis/SKILL.md").exists()


def test_unsafe_skills_warn_without_breaking_eligible_sync(workspace):
    skills = workspace / "planets/demo/skills"
    strange = skills / "invalid name"
    strange.mkdir()
    (strange / "SKILL.md").write_text("---\ndescription: Invalid ID\n---")
    outside = workspace.parent / "outside.md"
    outside.write_text("private")
    escaped = skills / "escape"
    escaped.mkdir()
    (escaped / "SKILL.md").symlink_to(outside)
    result = publish(workspace)
    assert result.returncode == 0, result.stderr
    assert "WARNING: skipping" in result.stderr
    assert (workspace / ".agents/skills/demo:analysis/SKILL.md").exists()
    assert not (workspace / ".agents/skills/demo:escape").exists()
    assert "demo:escape" not in inventory(workspace, CORE)
