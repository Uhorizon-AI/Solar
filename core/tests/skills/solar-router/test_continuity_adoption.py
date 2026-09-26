"""The router and continuity_cli adopt the record older versions left under sun/runtime."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

import continuity_cli
import continuity_store
import router


def _write(path, task, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"active_task": task}), encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _legacy(runtime):
    return continuity_store.legacy_path(runtime.workspace)


def _backups(runtime):
    return sorted(_legacy(runtime).parent.glob("active.json.migrated-*"))


def _seed(task, updated_at):
    import solar_state
    with solar_state.session() as store:
        store.continuity_import_text(json.dumps({"active_task": task}) + "\n")
        store.conn.execute(
            "UPDATE continuity SET updated_at = ? WHERE id = 1", (updated_at,))


def test_newer_legacy_record_wins_and_is_kept_as_backup(isolated_runtime):
    _seed("old intention", "1970-01-01T00:00:00Z")
    _write(_legacy(isolated_runtime), "live intention", 2_000)

    assert router.load_continuity()["active_task"] == "live intention"
    assert not _legacy(isolated_runtime).exists()
    assert len(_backups(isolated_runtime)) == 1


def test_older_legacy_record_does_not_overwrite(isolated_runtime):
    _seed("current intention", "2099-01-01T00:00:00Z")
    _write(_legacy(isolated_runtime), "stale intention", 1_000)

    assert router.load_continuity()["active_task"] == "current intention"
    assert not _legacy(isolated_runtime).exists()
    assert len(_backups(isolated_runtime)) == 1


def test_legacy_only_is_adopted(isolated_runtime):
    _write(_legacy(isolated_runtime), "only intention", 1_000)

    assert router.load_continuity()["active_task"] == "only intention"
    assert not _legacy(isolated_runtime).exists()


def test_nothing_to_adopt_changes_nothing(isolated_runtime):
    assert router.load_continuity() is None
    assert not isolated_runtime.continuity.exists()


def test_cli_set_before_the_first_turn_keeps_the_live_record(isolated_runtime, monkeypatch):
    """A set must not make a stale row look newer than the live legacy record."""
    _seed("old intention", "1970-01-01T00:00:00Z")
    _write(_legacy(isolated_runtime), "live intention", 2_000)
    monkeypatch.setattr(continuity_cli, "SOLAR_WORKSPACE", isolated_runtime.workspace)

    args = argparse.Namespace(
        task=None, owner="louis", channel=None, pending=[], decision=[],
        completed=[], constraint=[], replace_pending=None)
    continuity_cli.cmd_set(args)

    data = router.load_continuity()
    assert data["active_task"] == "live intention"
    assert data["next_owner"] == "louis"


def test_a_recreated_legacy_file_never_overwrites_the_first_backup(isolated_runtime):
    """An old router still running during the update can write sun/ again."""
    _write(_legacy(isolated_runtime), "first", 1_000)
    router.load_continuity()
    first = _backups(isolated_runtime)
    first_content = first[0].read_text(encoding="utf-8")

    # Written by the old router after the adoption, so newer than the runtime copy.
    _write(_legacy(isolated_runtime), "second", time.time() + 60)
    assert router.load_continuity()["active_task"] == "second"

    backups = _backups(isolated_runtime)
    assert len(backups) == 2
    assert first[0] in backups and first[0].read_text(encoding="utf-8") == first_content


def _adopt_in_child(workspace, runtime, barrier, results):
    os.environ["SOLAR_RUNTIME_ROOT"] = runtime
    barrier.wait()
    results.put(continuity_store.adopt_legacy(workspace, Path(runtime)))


def test_concurrent_adoptions_have_one_winner(tmp_path, monkeypatch):
    workspace, runtime = tmp_path / "ws", tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(runtime))
    import solar_state
    with solar_state.cutover(runtime) as cut:
        cut.upgrade_schema()
        cut.set_format("sqlite")
    _write(continuity_store.legacy_path(workspace), "live intention", 2_000)

    ctx = multiprocessing.get_context("spawn")
    workers = 8
    barrier, results = ctx.Barrier(workers), ctx.Queue()
    procs = [ctx.Process(target=_adopt_in_child, args=(str(workspace), str(runtime), barrier, results))
             for _ in range(workers)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(30)
    outcomes = sorted(results.get(timeout=5) for _ in range(workers))

    # One winner. The rest find the file already gone ("none") or hit a
    # transient lock/disk error ("failed"), which the next turn retries.
    assert outcomes.count("adopted") == 1
    assert set(outcomes) <= {"adopted", "none", "failed"}
    with solar_state.session() as store:
        assert store.continuity_get()["active_task"] == "live intention"
    assert len(list(continuity_store.legacy_path(workspace).parent.glob("active.json.migrated-*"))) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_disk_error_is_audited_and_the_turn_goes_on(isolated_runtime):
    _seed("old intention", "1970-01-01T00:00:00Z")
    _write(_legacy(isolated_runtime), "live intention", 2_000)
    folder = _legacy(isolated_runtime).parent
    folder.chmod(0o500)
    try:
        data = router.load_continuity()
    finally:
        folder.chmod(0o700)

    assert data["active_task"] == "old intention"
    assert _legacy(isolated_runtime).exists(), "the legacy record must survive a failed adoption"
    import solar_state
    with solar_state.session() as store:
        events = store.audit_rows()
    assert any(row["event"] == "continuity_adoption_failed" for row in events)

    # Next call, with the disk writable again, finishes the job.
    assert router.load_continuity()["active_task"] == "live intention"
