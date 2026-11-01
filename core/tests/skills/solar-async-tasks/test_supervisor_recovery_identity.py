"""Recovery identity regressions: advance the clock, never signal real processes."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from supervisor_support import CORE_ROOT  # puts the skill scripts on sys.path
import supervisor as mod


@pytest.fixture
def recovery(rig, monkeypatch):
    clock = {"now": 1005.0}
    process = {"kind": "alive", "epoch": 1001.0, "members": [300]}
    stopped, failed = [], []
    monkeypatch.setattr(mod.time, "time", lambda: clock["now"])
    monkeypatch.setattr(mod.lib, "matches", lambda *args: ("gone", {}))
    monkeypatch.setattr(mod.lib, "probe", lambda pid: (process["kind"], {"epoch": process["epoch"]}))
    monkeypatch.setattr(mod, "group_members", lambda pgid: process["members"] if pgid == 300 else [])

    def stop(pgid, *args):
        stopped.append(pgid)
        process["members"] = []
        return True

    monkeypatch.setattr(mod, "stop_group", stop)

    @contextmanager
    def session():
        yield SimpleNamespace(task_get=lambda task: {"pid": 300})

    def build():
        sup = rig.build()
        monkeypatch.setattr(sup, "_session", session)
        monkeypatch.setattr(sup, "_lease_expired", lambda row: False)
        monkeypatch.setattr(sup, "_fail", lambda task, token, reason, detail: failed.append(reason))
        return sup

    row = dict(task_id="lost", token="fixture", owner_pid=200, owner_started="original")
    record = dict(task_id="lost", token="fixture", worker="old-supervisor", pid=200,
                  pgid=200, provider_pid=300, started="original", dispatched_epoch=1000.0, access={})
    return SimpleNamespace(build=build, row=row, record=record, clock=clock, process=process,
                           stopped=stopped, failed=failed)


@pytest.mark.parametrize("delay", [5, 60, 3600])
def test_delayed_recovery_uses_original_dispatch_time(recovery, delay):
    r = recovery
    r.clock["now"] = 1000.0 + delay
    sup = r.build()
    sup._examine(r.row, r.record, startup=True)
    assert r.stopped == [300]
    assert r.failed == ["executor_lost"]
    assert not sup.blocked


def test_blocked_evidence_survives_sweeps_disk_and_another_restart(recovery):
    r = recovery
    sup = r.build()
    r.process["members"] = None
    sup._examine(r.row, r.record, startup=True)
    for now in (1060.0, 1120.0):
        r.clock["now"] = now
        sup._examine(r.row, dict(sup.blocked["lost"]), startup=False)
        assert sup.blocked["lost"]["dispatched_epoch"] == 1000.0
        assert sup.blocked["lost"]["provider_pid"] == 300
    sup._save_records()
    again = r.build()
    again._load_blocked()
    record = dict(again.blocked["lost"])
    assert record["dispatched_epoch"] == 1000.0 and record["provider_pid"] == 300
    r.process["members"] = [300]
    again._examine(r.row, record, startup=True)
    assert r.stopped == [300] and r.failed == ["executor_lost"]


def test_adopted_execution_keeps_original_dispatch_time(recovery, monkeypatch):
    r = recovery
    monkeypatch.setattr(mod.lib, "matches", lambda *args: ("alive", {}))
    sup = r.build()
    sup._examine(r.row, r.record, startup=True)
    adopted = sup.children["lost"]
    assert adopted.dispatched_epoch == 1000.0
    assert sup._provider_group(adopted, immediate=False) == ("alive", 300)
    assert adopted.record()["dispatched_epoch"] == 1000.0


@pytest.mark.parametrize("evidence", [None, "1000", True, 0, -1, 1002.0, float("nan"), float("inf"), 10**400])
def test_invalid_dispatch_evidence_never_authorizes_a_signal(recovery, evidence):
    r = recovery
    r.clock["now"] = 1001.5
    r.record["dispatched_epoch"] = evidence
    sup = r.build()
    sup._examine(r.row, r.record, startup=True)
    assert r.stopped == [] and r.failed == []
    assert sup.blocked["lost"]["reason"] == "group_uncertain"
    assert sup.blocked["lost"]["dispatched_epoch"] is None


def test_adoption_without_dispatch_evidence_reports_unknown_time(recovery, monkeypatch):
    r = recovery
    del r.record["dispatched_epoch"]
    monkeypatch.setattr(mod.lib, "matches", lambda *args: ("alive", {}))
    sup = r.build()
    sup._examine(r.row, r.record, startup=True)
    adopted = sup.children["lost"]
    assert adopted.view()["since"] is None
    assert sup._provider_group(adopted, immediate=False) == ("uncertain", 300)
    assert r.stopped == []


@pytest.mark.parametrize("kind,epoch", [("alive", 900.0), ("gone", 1001.0), ("unknown", 1001.0)])
def test_foreign_or_unproven_provider_group_remains_blocked(recovery, kind, epoch):
    r = recovery
    r.process.update(kind=kind, epoch=epoch)
    sup = r.build()
    sup._examine(r.row, r.record, startup=True)
    assert r.stopped == [] and r.failed == []
    assert sup.blocked["lost"]["reason"] == "group_uncertain"
