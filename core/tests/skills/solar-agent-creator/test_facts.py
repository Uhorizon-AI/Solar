from concurrent.futures import ThreadPoolExecutor
import sqlite3
import shutil
import json
import subprocess
from pathlib import Path

import pytest

import agent_memory as memory
import fact_store


@pytest.fixture
def planet(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "planets/demo"
    (root / "agents").mkdir(parents=True)
    for agent in ("sales", "product"):
        (root / f"agents/{agent}.md").write_text("Contract")
    (root / "evidence.md").write_text("Verified result")
    approval = workspace / "sun/plans/approved.md"
    approval.parent.mkdir(parents=True)
    approval.write_text("# Execution memory\n\nOwner approved initialization for demo/sales: observed repeated execution-history queries across sessions cannot be served by the existing files.\n")
    return workspace, root


def init(planet):
    return fact_store.initialize(planet[0], "demo", "sales", "sun/plans/approved.md#execution-memory")


def append(planet, agent="sales", event="event"):
    return fact_store.append(planet[0], "demo", agent, "follow-up", event,
                             "succeeded", "evidence.md", "2026-01-01T00:00:00+00:00")


def test_no_automatic_initialization_or_crm_copy(planet):
    with pytest.raises(ValueError, match="absent"):
        fact_store.read(planet[0], "demo", "sales", "follow-up")
    assert not (planet[1] / ".solar").exists()
    with pytest.raises(ValueError, match="need"):
        fact_store.initialize(planet[0], "demo", "sales", "")
    init(planet)
    assert append(planet)["created"]
    assert not append(planet)["created"]
    record = fact_store.read(planet[0], "demo", "sales", "follow-up")["facts"][0]
    assert record["source_verified"]
    assert "body" not in record and "summary" not in record
    assert fact_store.read(planet[0], "demo", "product", "follow-up")["facts"] == []
    assert fact_store.read(planet[0], "demo", "sales", "other")["facts"] == []


def test_concurrent_writes_and_conflicting_retry(planet):
    init(planet)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: append(planet, event=f"event-{i}"), range(12)))
    assert all(row["created"] for row in results)
    (planet[1] / "evidence.md").write_text("Changed result")
    with pytest.raises(ValueError, match="different"):
        append(planet, event="event-1")
    assert all(not row["source_verified"] for row in fact_store.read(planet[0], "demo", "sales", "follow-up")["facts"])


def test_backup_restore_preserves_current_state_and_refuses_stale_hash(planet):
    init(planet)
    append(planet)
    saved = fact_store.backup(planet[0], "demo", "sales")
    append(planet, event="event-2")
    path = planet[1] / ".solar/agent-memory.sqlite"
    old = memory.file_hash(path)
    relative = str(memory.Path(saved["path"]).relative_to(planet[1]))
    with pytest.raises(ValueError, match="changed"):
        fact_store.restore_backup(planet[0], "demo", "sales", relative, "0" * 64)
    restored = fact_store.restore_backup(planet[0], "demo", "sales", relative, old)
    assert len(fact_store.read(planet[0], "demo", "sales", "follow-up")["facts"]) == 1
    assert memory.file_hash(memory.Path(restored["previous_state_backup"]["path"])) == old


def test_schema_git_exclusion_and_symlinks_refuse(planet):
    (planet[1] / ".git").mkdir()
    with pytest.raises(ValueError, match="ignore"):
        init(planet)
    (planet[1] / ".gitignore").write_text(".solar/\n")
    init(planet)
    with sqlite3.connect(planet[1] / ".solar/agent-memory.sqlite") as db:
        db.execute("PRAGMA user_version = 999")
    with pytest.raises(ValueError, match="schema"):
        fact_store.read(planet[0], "demo", "sales", "follow-up")


@pytest.mark.parametrize("source", ["../outside", "/tmp/outside", "planets/other/evidence.md"])
def test_external_fact_sources_refuse(planet, source):
    init(planet)
    with pytest.raises(ValueError):
        fact_store.append(planet[0], "demo", "sales", "follow-up", "bad", "failed",
                          source, "2026-01-01T00:00:00+00:00")
    assert fact_store.read(planet[0], "demo", "sales", "follow-up")["facts"] == []


def test_database_copied_to_other_planet_refuses(planet):
    init(planet)
    append(planet)
    other = planet[0] / "planets/other"
    shutil.copytree(planet[1], other)
    with pytest.raises(ValueError, match="another planet"):
        fact_store.read(planet[0], "other", "sales", "follow-up")


@pytest.mark.parametrize("approval", ["Observed recurring execution queries", "sun/plans/missing.md#execution-memory", "sun/plans/approved.md#missing", "../outside.md#execution-memory"])
def test_need_requires_existing_approval_reference(planet, approval):
    with pytest.raises(ValueError):
        fact_store.initialize(planet[0], "demo", "sales", approval)
    assert not (planet[1] / ".solar").exists()


def test_facts_wrapper_dispatch_all_verbs(planet):
    core = Path(__file__).resolve().parents[3]
    wrapper = core / "skills/solar-client/scripts/solar"
    def cli(verb, *args):
        result = subprocess.run(["bash", str(wrapper), "agent", "--workspace", str(planet[0]),
                                 "facts", verb, "--planet", "demo", "--agent", "sales", *args],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert cli("init", "--need", "sun/plans/approved.md#execution-memory")["created"]
    assert cli("append", "--responsibility", "follow.up", "--event-id", "event.1",
               "--result", "succeeded", "--source", "evidence.md",
               "--observed-at", "2026-01-01T00:00:00+00:00")["created"]
    assert len(cli("read", "--responsibility", "follow.up")["facts"]) == 1
    saved = cli("backup")
    path = planet[1] / ".solar/agent-memory.sqlite"
    reference = str(Path(saved["path"]).relative_to(planet[1]))
    assert cli("restore", "--source", reference,
               "--expected-current-sha256", memory.file_hash(path))["restored"]


def test_connections_closed_before_database_replacement(planet, monkeypatch):
    opened = []
    connect = sqlite3.connect
    class Tracked(sqlite3.Connection):
        closed = False
        def close(self):
            self.closed = True
            super().close()
    def tracked(*args, **kwargs):
        conn = connect(*args, **kwargs, factory=Tracked)
        opened.append(conn)
        return conn
    monkeypatch.setattr(sqlite3, "connect", tracked)
    init(planet)
    assert all(conn.closed for conn in opened)
    saved = fact_store.backup(planet[0], "demo", "sales")
    assert all(conn.closed for conn in opened)
    path = planet[1] / ".solar/agent-memory.sqlite"
    fact_store.restore_backup(planet[0], "demo", "sales",
                              str(Path(saved["path"]).relative_to(planet[1])), memory.file_hash(path))
    assert all(conn.closed for conn in opened)
