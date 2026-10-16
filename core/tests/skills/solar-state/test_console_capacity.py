"""What the console shows about capacity: places used, what runs at once, why the rest waits, and
the applied configuration with the differences a proposal would make. Reads only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import solar_state
import runtime_views
from test_reservations import PROFILE, make, access, set_policy, verified_profile  # noqa: F401  (the autouse fixture too)

_APP = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))
import console_data  # noqa: E402


@pytest.fixture
def scene(ready):
    """Three places, codex limited to one: two running, one free, and a task of every kind of wait."""
    with solar_state.session(ready, auto_backup=False) as s:
        set_policy(s, global_capacity=3, provider_capacity={"codex": 1})
        r1 = make(s, "R1", policy=access(), provider="codex")
        r2 = make(s, "R2", policy=access(), provider="codex")
        r3 = make(s, "R3", policy=access(resources=["browser"]), provider="claude")
        r4 = make(s, "R4", policy=access(resources=["browser"]), provider="claude")
        r5 = make(s, "R5", policy=access(), provider="claude")
        r6 = make(s, "R6", policy=access(), provider="claude")
        legacy = make(s, "Legacy", policy=None)
        dep = make(s, "Dep", policy=access(), provider="claude", blocked_by_task_ids=json.dumps(r1))
        assert s.task_claim_detail(r1, "w")["claimed"] and s.task_claim_detail(r3, "w")["claimed"]
        yield dict(root=ready, r1=r1, r2=r2, r3=r3, r4=r4, r5=r5, r6=r6, legacy=legacy, dep=dep)


def test_places_used_what_runs_and_why_the_rest_waits(scene):
    with solar_state.read_session(scene["root"]) as store:           # a read session: nothing may be written
        data = runtime_views.console_capacity(store, supervisor={"blocked": [
            {"task_id": "stuck", "reason": "group_uncertain", "detail": "members left", "since": "2026-10-16T10:00:00Z"}]})
    assert data["capacity"] == dict(used=2, global_capacity=3, provider_capacity={"codex": 1},
                                    simultaneous=2, free=1)
    assert {r["id"] for r in data["running"]} == {scene["r1"], scene["r3"]}
    kinds = {w["id"]: w["kind"] for w in data["waiting"]}
    assert kinds[scene["dep"]] == "dependency"
    assert kinds[scene["r2"]] == "provider"           # codex has one place and r1 holds it
    assert kinds[scene["r4"]] == "resource"           # r3 holds the browser
    assert scene["r5"] not in kinds                   # the free place: it would start on the next pass
    assert kinds[scene["r6"]] == "capacity"           # ...and then all three are used
    assert kinds[scene["legacy"]] == "capacity"       # a task that runs alone waits for an idle machine
    assert data["recovery"][0]["id"] == "stuck" and data["wait_counts"]["recovery"] == 1
    assert data["wait_counts"]["dependency"] == 1 and data["wait_counts"]["provider"] == 1


def test_the_waits_change_when_a_place_frees_up(scene):
    with solar_state.session(scene["root"], auto_backup=False) as s:
        token = next(r["token"] for r in s.reservations() if r["task_id"] == scene["r3"])
        s.task_complete(scene["r3"], token=token)
    with solar_state.read_session(scene["root"]) as store:
        data = runtime_views.console_capacity(store)
    kinds = {w["id"]: w["kind"] for w in data["waiting"]}
    assert data["capacity"]["used"] == 1 and scene["r4"] not in kinds       # the browser is free: it would start
    assert kinds[scene["r2"]] == "provider" and scene["r5"] not in kinds


def test_the_applied_revision_and_the_pending_differences(scene):
    proposal = scene["root"] / "async-tasks" / "config" / "async-execution.json"
    proposal.parent.mkdir(parents=True, exist_ok=True)
    proposal.write_text(json.dumps(dict(schema_version=1, revision=2, global_capacity=4,
                                        provider_capacity={"codex": 1}, exclusive_wait_seconds=60,
                                        enabled_reader_profiles=[PROFILE])))
    with solar_state.read_session(scene["root"]) as store:
        config = runtime_views.console_capacity(store)["configuration"]
    assert config["applied"]["revision"] == 1 and config["applied"]["global_capacity"] == 3
    assert config["pending"] is True
    assert config["differences"]["global_capacity"] == dict(applied=3, proposed=4)
    assert config["proposal"]["error"] is None
    # nothing was applied by looking
    with solar_state.session(scene["root"], auto_backup=False) as s:
        assert s.async_policy()["global_capacity"] == 3
    proposal.write_text("{not json")
    with solar_state.read_session(scene["root"]) as store:
        broken = runtime_views.console_capacity(store)["configuration"]
    assert broken["applied"]["revision"] == 1 and broken["proposal"]["error"]


def test_maintenance_is_a_recovery_wait(scene):
    (scene["root"] / "maintenance.json").write_text(json.dumps(dict(operation="update")))
    with solar_state.read_session(scene["root"]) as store:
        data = runtime_views.console_capacity(store)
    assert data["waiting"] and {w["kind"] for w in data["waiting"]} == {"recovery"}


def test_the_console_reads_the_published_supervisor_without_probing_it(scene, monkeypatch, tmp_path):
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(scene["root"]))
    locks = scene["root"] / "async-tasks" / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    assert console_data.capacity(tmp_path)["supervisor"] is None
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (locks / "supervisor.json").write_text(json.dumps(dict(
        state="ready", pid=1234, started_at=now, heartbeat_at=now, reconciled=True,
        blocked=[dict(task_id="x", reason="cleanup_failed")], children=[])))
    data = console_data.capacity(tmp_path)
    assert data["supervisor"]["fresh"] is True and data["supervisor"]["state"] == "ready"
    assert data["recovery"][0]["reason"] == "cleanup_failed"
    (locks / "supervisor.json").write_text(json.dumps(dict(state="ready", pid=1234, heartbeat_at="2020-01-01T00:00:00Z")))
    assert console_data.capacity(tmp_path)["supervisor"]["fresh"] is False


def test_wait_kinds():
    kinds = runtime_views.wait_kind
    assert kinds(None) is None and kinds("resource:browser") == "resource" and kinds("scope_conflict") == "resource"
    assert kinds("blocked_by_dependency") == "dependency" and kinds("provider_capacity") == "provider"
    assert kinds("global_capacity") == kinds("drain_barrier") == kinds("exclusive_needs_idle") == "capacity"
    assert kinds("maintenance") == kinds("parent_revoked") == "recovery" and kinds("outside_schedule") == "other"


def test_queue_waits_gives_the_answers_a_claim_gives(ready):
    """The console's reasons come from the claim's own rules: for the same queue, what it says would
    start is what a claim starts (in order), and what it says is waiting is what a claim reports."""
    with solar_state.session(ready, auto_backup=False) as s:
        set_policy(s, global_capacity=3, provider_capacity={"codex": 1})
        run1 = make(s, "A run", policy=access(), provider="codex")
        assert s.task_claim_detail(run1, "w")["claimed"]
        make(s, "B provider", policy=access(), provider="codex")           # codex is full
        make(s, "C free one", policy=access(), provider="claude")           # would start
        make(s, "D free two", policy=access(resources=["x"]), provider="claude")   # would start
        make(s, "E full", policy=access(), provider="claude")               # then nothing is left
        make(s, "F depends", policy=access(), provider="claude", blocked_by_task_ids=json.dumps(run1))
        stale = make(s, "G stale approval", policy=access(), provider="claude")
        s.conn.execute("UPDATE tasks SET body = body || ? WHERE id = ?", ("\nchanged after approval\n", stale))
        make(s, "H recurring soon", policy=access(), provider="claude", recurring="true",
             recurring_min_interval="86400", recurring_last_run=json.dumps("2999-01-01T00:00:00Z"))
        before = {w["id"]: w["reason"] for w in s.queue_waits()}
        audit_before = s.conn.execute("SELECT count(*) FROM audit").fetchone()[0]
    assert before["b-provider"] == "provider_capacity" and before["f-depends"] == "blocked_by_dependency"
    assert before["g-stale-approval"] in ("mismatch", "legacy", "absent")
    assert before["h-recurring-soon"] == "recurring_interval"
    would_start = [t for t, r in before.items() if r is None]
    assert would_start == ["c-free-one", "d-free-two"] and before["e-full"] == "global_capacity"
    with solar_state.read_session(ready) as store:                    # asking changed nothing
        assert store.conn.execute("SELECT count(*) FROM audit").fetchone()[0] == audit_before
    with solar_state.session(ready, auto_backup=False) as s:
        claimed = []
        while True:
            task = s.task_claim_next("w")
            if task is None:
                break
            claimed.append(task["id"])
        assert claimed == would_start
        after = {w["id"]: w["reason"] for w in s.queue_waits()}
        waiting = {w["id"]: w["reason"] for w in s.task_claim_next_detail("w")["waiting"]}
    assert waiting and all(after[t] == r for t, r in waiting.items())


def test_the_console_judges_the_heartbeat_with_the_same_threshold_as_the_check(scene, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("SOLAR_RUNTIME_ROOT", str(scene["root"]))
    locks = scene["root"] / "async-tasks" / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    beat = (datetime.now(timezone.utc) - timedelta(seconds=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (locks / "supervisor.json").write_text(json.dumps(dict(state="ready", pid=1, heartbeat_at=beat, reconciled=True)))
    assert console_data.capacity(tmp_path)["supervisor"]["fresh"] is False                 # 45 s > the default 30 s
    monkeypatch.setenv("SOLAR_SUPERVISOR_HEARTBEAT_STALE", "120")                           # what check_async_tasks sees too
    assert console_data.capacity(tmp_path)["supervisor"]["fresh"] is True
