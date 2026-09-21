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


def test_newer_legacy_record_wins_and_is_kept_as_backup(isolated_runtime):
    _write(isolated_runtime.continuity, "old intention", 1_000)
    _write(_legacy(isolated_runtime), "live intention", 2_000)

    assert router.load_continuity()["active_task"] == "live intention"
    assert not _legacy(isolated_runtime).exists()
    assert len(_backups(isolated_runtime)) == 1


def test_older_legacy_record_does_not_overwrite(isolated_runtime):
    _write(isolated_runtime.continuity, "current intention", 2_000)
    _write(_legacy(isolated_runtime), "stale intention", 1_000)

    assert router.load_continuity()["active_task"] == "current intention"
    assert not _legacy(isolated_runtime).exists()
    assert len(_backups(isolated_runtime)) == 1


def test_legacy_only_is_adopted(isolated_runtime):
    _write(_legacy(isolated_runtime), "only intention", 1_000)

    assert router.load_continuity()["active_task"] == "only intention"
    assert isolated_runtime.continuity.exists()


def test_nothing_to_adopt_changes_nothing(isolated_runtime):
    assert router.load_continuity() is None
    assert not isolated_runtime.continuity.exists()


def test_cli_set_before_the_first_turn_keeps_the_live_record(isolated_runtime, monkeypatch):
    """A `set` on the stale runtime copy must not make it look newer than the live one."""
    _write(isolated_runtime.continuity, "old intention", 1_000)
    _write(_legacy(isolated_runtime), "live intention", 2_000)
    monkeypatch.setattr(continuity_cli, "ACTIVE", isolated_runtime.continuity)
    monkeypatch.setattr(continuity_cli, "SOLAR_WORKSPACE", isolated_runtime.workspace)

    args = argparse.Namespace(
        task=None, owner="louis", channel=None, pending=[], decision=[],
        completed=[], constraint=[], replace_pending=None)
    continuity_cli.cmd_set(args)

    data = json.loads(isolated_runtime.continuity.read_text(encoding="utf-8"))
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


def _adopt_in_child(workspace, active, barrier, results):
    barrier.wait()
    results.put(continuity_store.adopt_legacy(workspace, Path(active)))


def test_concurrent_adoptions_have_one_winner(tmp_path):
    workspace, active = tmp_path / "ws", tmp_path / "runtime" / "continuity" / "active.json"
    _write(active, "old intention", 1_000)
    _write(continuity_store.legacy_path(workspace), "live intention", 2_000)

    ctx = multiprocessing.get_context("spawn")
    workers = 8
    barrier, results = ctx.Barrier(workers), ctx.Queue()
    procs = [ctx.Process(target=_adopt_in_child, args=(str(workspace), str(active), barrier, results))
             for _ in range(workers)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(30)
    outcomes = sorted(results.get(timeout=5) for _ in range(workers))

    assert outcomes.count("adopted") == 1
    assert outcomes.count("none") == workers - 1
    assert json.loads(active.read_text(encoding="utf-8"))["active_task"] == "live intention"
    assert len(list(active.parent.parent.glob("**/active.json.migrated-*"))) == 0
    assert len(list(continuity_store.legacy_path(workspace).parent.glob("active.json.migrated-*"))) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_disk_error_is_audited_and_the_turn_goes_on(isolated_runtime):
    _write(isolated_runtime.continuity, "old intention", 1_000)
    _write(_legacy(isolated_runtime), "live intention", 2_000)
    folder = isolated_runtime.continuity.parent
    folder.chmod(0o500)
    try:
        data = router.load_continuity()
    finally:
        folder.chmod(0o700)

    assert data["active_task"] == "old intention"
    assert _legacy(isolated_runtime).exists(), "the legacy record must survive a failed adoption"
    events = [json.loads(line) for line in
              isolated_runtime.audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(row["event"] == "continuity_adoption_failed" for row in events)

    # Next call, with the disk writable again, finishes the job.
    assert router.load_continuity()["active_task"] == "live intention"
