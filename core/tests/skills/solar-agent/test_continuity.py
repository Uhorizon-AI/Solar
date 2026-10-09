import json
import shutil
import subprocess
import sys

import pytest

import agent_memory as memory
import solar_state
from runtime_owner import claim_test_owner


@pytest.fixture
def source(tmp_path, monkeypatch):
    workspace, runtime = tmp_path / "source", tmp_path / "runtime"
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    owner = claim_test_owner(runtime, workspace, monkeypatch=monkeypatch)
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    planet = workspace / "planets/demo"
    (planet / "agents").mkdir(parents=True)
    (planet / "agents/sales.md").write_text("Canonical contract\n")
    (planet / "result.md").write_text("An existing verified effect\n")
    cp = {"checkpoint": {"state": "effect_uncertain", "artifact_ref": "planets/demo/result.md",
                         "expected_sha256": memory.file_hash(planet / "result.md")},
          "last_verified_result": {"path": "planets/demo/result.md",
                                   "sha256": memory.file_hash(planet / "result.md")},
          "next_check": {"at": "2099-01-01", "action": "Read response", "source": "planets/demo/agents/sales.md"},
          "wait": "Await owner decision",
          "decision": {"status": "pending", "owner": "owner", "source": "planets/demo/agents/sales.md",
                       "valid_until": "2099-01-01T00:00:00+00:00"}}
    fields = {"workspace_id": owner["workspace_id"], "planet": "demo", "agent": "sales",
              "responsibility": "follow-up", "agent_contract": "planets/demo/agents/sales.md",
              "continuity_checkpoint": cp}
    with solar_state.session() as state:
        state.task_create([(k, json.dumps(v)) for k, v in fields.items()], task_id="proof")
    return workspace, runtime, planet, cp


def read(source):
    return memory.show(source[0], "demo", "sales", "follow-up", "proof")


def copy_to_destination(source, tmp_path, monkeypatch):
    destination, runtime = tmp_path / "destination", tmp_path / "destination-runtime"
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    claim_test_owner(runtime, destination, monkeypatch=monkeypatch)
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format(solar_state.FORMAT_SQLITE)
    shutil.copytree(source[2], destination / "planets/demo")
    return destination


def test_read_and_export_never_repeat_effect(source):
    before = (source[2] / "result.md").stat()
    with solar_state.read_session() as state:
        original = state.task_export("proof")
    assert read(source)["continuity_checkpoint"] == source[3]
    result = memory.export(source[0], "demo", "sales", "follow-up", "proof")
    assert result["changed"]
    assert not memory.export(source[0], "demo", "sales", "follow-up", "proof")["changed"]
    with solar_state.read_session() as state:
        assert state.task_export("proof") == original
    after = (source[2] / "result.md").stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


@pytest.mark.parametrize("field,value", [("planet", "other"), ("agent", "other"),
                                        ("responsibility", "other"), ("workspace_id", "other")])
def test_identity_refuses(source, field, value):
    with solar_state.session() as state:
        state.task_set("proof", field, json.dumps(value))
    with pytest.raises(ValueError, match="match"):
        read(source)


def test_portable_restore_keeps_authority_empty_and_tasks_absent(source, tmp_path, monkeypatch):
    memory.export(source[0], "demo", "sales", "follow-up", "proof")
    destination = copy_to_destination(source, tmp_path, monkeypatch)
    result = memory.restore(destination, "demo", "sales")
    assert result["ready"] and not result["applied"] and not result["retry_authorized"]
    assert result["payload"]["checkpoint"]["checkpoint"]["artifact_ref"] == "result.md"
    memory.restore(destination, "demo", "sales", apply=True)
    memory.restore(destination, "demo", "sales", apply=True)
    with solar_state.read_session() as state:
        assert state.task_list() == []
        record = state.continuity_get()["portable_agents"]["demo:sales:follow-up"]
        assert record["authority"] == "none"
        assert record["origin"]["origin_workspace"] != record["destination_workspace"]


def test_changed_artifact_blocks_incorporation(source, tmp_path, monkeypatch):
    memory.export(source[0], "demo", "sales", "follow-up", "proof")
    destination = copy_to_destination(source, tmp_path, monkeypatch)
    (destination / "planets/demo/result.md").write_text("Changed effect")
    result = memory.restore(destination, "demo", "sales")
    assert not result["ready"] and result["issues"]
    with pytest.raises(ValueError, match="decision"):
        memory.restore(destination, "demo", "sales", apply=True)
    with solar_state.read_session() as state:
        assert state.continuity_get() is None


@pytest.mark.parametrize("reference", ["../secret", "/tmp/secret", "planets/other/result.md"])
def test_unsafe_reference_refuses(source, reference):
    cp = dict(source[3], next_check={"source": reference})
    with solar_state.session() as state:
        state.task_set("proof", "continuity_checkpoint", json.dumps(cp))
    with pytest.raises(ValueError):
        memory.export(source[0], "demo", "sales", "follow-up", "proof")
    assert not (source[2] / "agents/continuidad/sales.md").exists()


def test_existing_copy_is_not_overwritten(source):
    memory.export(source[0], "demo", "sales", "follow-up", "proof")
    cp = dict(source[3], wait="Changed wait")
    with solar_state.session() as state:
        state.task_set("proof", "continuity_checkpoint", json.dumps(cp))
    with pytest.raises(ValueError, match="different content"):
        memory.export(source[0], "demo", "sales", "follow-up", "proof")


def test_symlink_and_malformed_copy_refuse(source):
    (source[2] / "agents/continuidad").symlink_to(source[2].parent)
    with pytest.raises(ValueError, match="symlink"):
        memory.export(source[0], "demo", "sales", "follow-up", "proof")


def test_real_checkpoint_shape_projects_only_minimum(source):
    cp = dict(source[3], version=1, task_ref="sun/runtime/tasks/proof.md",
              sources=[{"path": "planets/demo/result.md", "sha256": memory.file_hash(source[2] / "result.md")}])
    cp["checkpoint"] = dict(cp["checkpoint"], effect="Do not copy effect text",
                            effect_writes_during_recovery=0, verified_at="2026-01-01")
    cp["decision"] = dict(cp["decision"], subject="Do not copy business subject", expiry_effect="review")
    with solar_state.session() as state:
        state.task_set("proof", "continuity_checkpoint", json.dumps(cp))
    memory.export(source[0], "demo", "sales", "follow-up", "proof")
    result = memory.restore(source[0], "demo", "sales")
    assert result["ready"]
    projected = result["payload"]["checkpoint"]
    assert "task_ref" not in projected and "effect" not in projected["checkpoint"]
    assert "subject" not in projected["decision"] and projected["sources"][0]["path"] == "result.md"


def test_expired_decision_and_missing_source_require_decision(source):
    cp = dict(source[3], decision=dict(source[3]["decision"], valid_until="2000-01-01T00:00:00+00:00"))
    with solar_state.session() as state:
        state.task_set("proof", "continuity_checkpoint", json.dumps(cp))
    memory.export(source[0], "demo", "sales", "follow-up", "proof")
    (source[2] / "result.md").unlink()
    result = memory.restore(source[0], "demo", "sales")
    assert not result["ready"] and len(result["issues"]) >= 3
    with pytest.raises(ValueError, match="decision"):
        memory.restore(source[0], "demo", "sales", apply=True)


def test_failed_write_cleans_temporary_file(source, monkeypatch):
    def fail(*args):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(memory.os, "replace", fail)
    with pytest.raises(OSError):
        memory.export(source[0], "demo", "sales", "follow-up", "proof")
    assert list((source[2] / "agents/continuidad").iterdir()) == []


def test_cli_reads_with_isolated_runtime_and_refuses_wrong_agent(source):
    script = str(memory.Path(memory.__file__))
    argv = [sys.executable, script, "--workspace", str(source[0]), "continuity", "show",
            "--planet", "demo", "--agent", "sales", "--responsibility", "follow-up", "--task-id", "proof"]
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["agent"] == "sales"


def test_corrupt_copy_refuses(source):
    copy = memory.export(source[0], "demo", "sales", "follow-up", "proof")
    path = memory.Path(copy["path"])
    path.write_text(path.read_text().replace("Await owner decision", "Corrupt decision"))
    with pytest.raises(ValueError, match="digest"):
        memory.restore(source[0], "demo", "sales")


@pytest.mark.parametrize("version", [2, True])
def test_unknown_copy_version_refuses(source, version):
    copy = memory.export(source[0], "demo", "sales", "follow-up", "proof")
    path = memory.Path(copy["path"])
    text = path.read_text()
    envelope = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    envelope["payload"]["version"] = version
    envelope["sha256"] = memory.digest(envelope["payload"])
    path.write_text("# Portable agent continuity\n\n```json\n" + memory.encoded(envelope) + "\n```\n")
    with pytest.raises(ValueError, match="version"):
        memory.restore(source[0], "demo", "sales")


def test_restore_apply_repeat_is_idempotent_and_conflicting_copy_refuses(source, tmp_path, monkeypatch):
    memory.export(source[0], "demo", "sales", "follow-up", "proof")
    destination = copy_to_destination(source, tmp_path, monkeypatch)
    script = str(memory.Path(memory.__file__))
    argv = [sys.executable, script, "--workspace", str(destination), "continuity", "restore",
            "--planet", "demo", "--agent", "sales", "--apply"]
    for _ in range(2):
        result = subprocess.run(argv, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    with solar_state.read_session() as state:
        assert len(state.continuity_get()["portable_agents"]) == 1
        assert state.task_list() == []
    path = destination / "planets/demo/agents/continuidad/sales.md"
    text = path.read_text()
    envelope = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    envelope["payload"]["checkpoint"]["wait"] = "Different recorded wait"
    envelope["sha256"] = memory.digest(envelope["payload"])
    path.write_text("# Portable agent continuity\n\n```json\n" + memory.encoded(envelope) + "\n```\n")
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 2 and "different continuity already incorporated" in result.stderr


def test_missing_runtime_owner_refuses_cleanly(source, monkeypatch):
    # Use an existing read session so the test reaches the helper itself.
    with solar_state.read_session() as state:
        monkeypatch.setattr(solar_state, "_read_owner_file", lambda root: None)
        with pytest.raises(ValueError, match="runtime owner missing"):
            state.agent_continuity("demo", "sales", "follow-up", "proof")


def test_dotted_task_and_responsibility_are_readable(source):
    with solar_state.session() as state:
        task = state.task_get("proof")
        fields = [(key, value) for key, value in task["frontmatter"] if key not in {"id", "status", "created", "responsibility"}]
        fields.append(("responsibility", json.dumps("follow.up")))
        state.task_create(fields, task_id="proof.1")
    assert memory.show(source[0], "demo", "sales", "follow.up", "proof.1")["task_id"] == "proof.1"
