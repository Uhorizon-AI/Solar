"""Reservations: one place per active task, taken in the claim's own transaction.

Covers the shared admission rules (capacity, provider limit, access scopes, resources, unknown
tasks), the execution token, the applied policy, the drain barrier, the maintenance barrier,
the new material keys of the approval digest, derived-authorization provenance and the legacy
subtask inventory.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import solar_state
from dead_process import dead_pid
from reservation_tokens import token_of
from solar_state import PolicyInvalid, StaleToken, TransitionRefused

SCRIPT = Path(solar_state.__file__)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def access(mode="read", scopes=(), resources=()):
    return json.dumps(dict(version=1, mode=mode, scopes=list(scopes), resources=list(resources)),
                      sort_keys=True, separators=(",", ":"))


PROFILE = "text_only_review_v1"


class _EveryProvider:
    def __contains__(self, _):
        return True


@pytest.fixture(autouse=True)
def verified_profile(monkeypatch):
    """No profile has a verified implementation yet (PR 3 delivers one). These tests stand in
    for that: they pretend `PROFILE` is enforced for every provider, so the admission rules
    for declared tasks can be exercised. The tests of the real, empty registry undo it."""
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {PROFILE: _EveryProvider()})


def make(store, title, *, policy=None, status="queued", profile=PROFILE, **extra):
    """An approved task. `policy` is the access declaration; without it the task is legacy.
    A declared task also names the execution profile (the one `set_policy` enables)."""
    fields = [("title", json.dumps(title))]
    if policy is not None:
        fields.append(("access_policy", policy))
        if profile:
            fields.append(("execution_profile", profile))
    fields += [(k, v) for k, v in extra.items()]
    task_id = store.task_create(fields, f"\n# {title}\n\nDo {title}.\n", task_id=title.lower().replace(" ", "-"))
    if status == "queued":
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"])
    return task_id


def set_policy(store, **changes):
    """Apply the next revision. The reader profile is enabled unless the test says otherwise."""
    current = store.async_policy()
    changes.setdefault("enabled_reader_profiles", [PROFILE])
    document = dict(schema_version=1, revision=current["revision"] + 1,
                    global_capacity=current["global_capacity"],
                    provider_capacity=current["provider_capacity"],
                    exclusive_wait_seconds=current["exclusive_wait_seconds"],
                    enabled_reader_profiles=current["enabled_reader_profiles"])
    document.update(changes)
    return store.async_policy_apply(document, actor="test")


def active_ids(store):
    return sorted(r[0] for r in store.conn.execute("SELECT id FROM tasks WHERE status = 'active'"))


def claim(store, task_id, worker="w"):
    return store.task_claim_detail(task_id, worker)


@pytest.fixture
def store(ready):
    with solar_state.session(ready, auto_backup=False) as s:
        yield s


# --------------------------------------------------------------------------
# the initial policy and the schema
# --------------------------------------------------------------------------

def test_a_new_base_starts_with_capacity_one(store):
    policy = store.async_policy()
    assert (policy["revision"], policy["global_capacity"]) == (0, 1)
    assert policy["provider_capacity"] == {} and policy["exclusive_wait_seconds"] == 60
    assert store.reservations() == []


def test_a_second_claim_waits_for_the_only_place(store):
    set_policy(store)                       # capacity 1, the reader profile enabled
    a, b = make(store, "A", policy=access()), make(store, "B", policy=access())
    first = claim(store, a)
    assert first["claimed"] and first["token"]
    assert claim(store, b) == dict(claimed=False, reason="global_capacity")
    assert store.task_claim_next("w") is None            # the worker is held by the same rule
    store.task_complete(a, token=first["token"])
    assert claim(store, b)["claimed"]


def test_every_way_into_active_takes_a_reservation(store):
    set_policy(store)
    a, b = make(store, "A", policy=access()), make(store, "B", policy=access())
    store.task_transition(a, "active")                   # the generic move is not a way around it
    assert store.reservation_for(a)["token"]
    with pytest.raises(TransitionRefused, match="global_capacity"):
        store.task_transition(b, "active")
    assert store.task_status(b) == "queued"


# --------------------------------------------------------------------------
# the token
# --------------------------------------------------------------------------

def test_completing_releasing_and_failing_need_the_current_token(store):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    for call in (lambda: store.task_complete(a),
                 lambda: store.task_complete(a, token="0" * 32),
                 lambda: store.task_fail(a, "boom", token="1" * 32),
                 lambda: store.task_release(a, "w", token="2" * 32),
                 lambda: store.task_await(a, ["c"], token="3" * 32),
                 lambda: store.task_record(a, pid=1, token="4" * 32),
                 lambda: store.task_transition(a, "completed", token="5" * 32)):
        with pytest.raises(StaleToken):
            call()
    assert store.task_status(a) == "active" and store.reservation_for(a)["token"] == token
    assert store.task_complete(a, token=token) == "completed"
    assert store.reservation_for(a) is None              # the place went back with the status


def test_a_token_that_was_replaced_cannot_finish_the_execution(store):
    a = make(store, "A", policy=access())
    old = claim(store, a)["token"]
    store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
    taken = store.task_adopt(a, "w2", identity=lambda pid: None)
    assert taken["adopted"] and taken["token"] != old
    with pytest.raises(StaleToken):
        store.task_complete(a, token=old)
    assert store.task_complete(a, token=taken["token"]) == "completed"


def test_release_returns_the_task_and_the_place(store):
    a, b = make(store, "A", policy=access()), make(store, "B", policy=access())
    token = claim(store, a)["token"]
    store.task_release(a, "w", token=token)
    assert store.task_status(a) == "queued" and store.reservation_for(a) is None
    assert claim(store, b)["claimed"]


def test_a_failed_start_gives_the_place_back(store):
    a, b = make(store, "A", policy=access()), make(store, "B", policy=access())
    token = claim(store, a)["token"]
    store.task_fail(a, "## Execution Error\nnope", token=token)
    assert store.task_status(a) == "error"
    assert claim(store, b)["claimed"]


# --------------------------------------------------------------------------
# adoption: who may take an execution over
# --------------------------------------------------------------------------

def test_adopt_refuses_a_live_owner_and_a_valid_lease(store):
    a = make(store, "A", policy=access())
    token = store.task_claim_next("w")["token"]
    store.reservation_attach(a, token, pid=os.getpid())
    assert store.task_adopt(a, "w2")["reason"] == "lease_valid"
    store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
    started = store.reservation_for(a)["owner_started"]
    assert store.task_adopt(a, "w2", identity=lambda pid: started)["reason"] == "owner_alive"
    assert store.reservation_for(a)["token"] == token
    # The same pid reused by another process (another start time) is not the owner.
    assert store.task_adopt(a, "w2", identity=lambda pid: "another start")["adopted"]


def test_adopt_takes_a_manual_activation_nobody_runs_yet(store):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]            # activate.sh: the worker will run it
    taken = store.task_adopt(a, "worker")
    assert taken["adopted"] and taken["token"] != token
    assert store.task_adopt(a, "other")["adopted"] is False


def test_adopt_takes_an_active_task_that_predates_reservations(store):
    a = make(store, "A", policy=access())
    store.conn.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (a,))
    assert store.reservations()[0]["legacy_active"] is True
    taken = store.task_adopt(a, "w")
    assert taken["adopted"]
    assert store.task_complete(a, token=taken["token"]) == "completed"


def test_an_active_task_without_a_reservation_counts_as_exclusive(store):
    set_policy(store, global_capacity=3)
    ghost = make(store, "Ghost", policy=access())
    store.conn.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (ghost,))
    b = make(store, "B", policy=access())
    assert claim(store, b) == dict(claimed=False, reason="blocked_by_exclusive")


def test_heartbeat_extends_the_lease(store):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
    store.reservation_heartbeat(a, token)
    assert store.reservation_for(a)["lease_expires_at"] > "2020"
    with pytest.raises(StaleToken):
        store.reservation_heartbeat(a, "9" * 32)


# --------------------------------------------------------------------------
# capacity and the applied policy
# --------------------------------------------------------------------------

def test_capacity_follows_the_applied_revision_for_every_entry_point(store):
    ids = [make(store, f"R{i}", policy=access(scopes=[f"/x/{i}"])) for i in range(4)]
    set_policy(store, global_capacity=3)
    assert claim(store, ids[0])["claimed"]                       # manual
    assert store.task_claim_next("w")["id"] == ids[1]            # worker
    assert claim(store, ids[2])["claimed"]
    assert claim(store, ids[3]) == dict(claimed=False, reason="global_capacity")
    assert store.task_claim_next("w") is None
    assert len(active_ids(store)) == 3


def test_lowering_capacity_lets_the_running_ones_finish(store):
    ids = [make(store, f"R{i}", policy=access()) for i in range(3)]
    set_policy(store, global_capacity=3)
    tokens = [claim(store, t)["token"] for t in ids]
    set_policy(store, global_capacity=1)
    assert len(active_ids(store)) == 3                           # nobody is killed
    extra = make(store, "Late", policy=access())
    assert claim(store, extra)["reason"] == "global_capacity"
    for task_id, token in zip(ids, tokens):
        store.task_complete(task_id, token=token)
    assert claim(store, extra)["claimed"]


def test_provider_limit_is_independent_of_the_provider_name_otherwise(store):
    set_policy(store, global_capacity=5, provider_capacity={"codex": 2})
    codex = [make(store, f"C{i}", policy=access(), provider=json.dumps("codex")) for i in range(3)]
    other = make(store, "Other", policy=access(), provider=json.dumps("claude"))
    assert [claim(store, t)["claimed"] for t in codex] == [True, True, False]
    assert claim(store, codex[2])["reason"] == "provider_capacity"
    assert claim(store, other)["claimed"]                        # another provider is not limited by codex's


def test_the_same_provider_can_fill_every_place_when_no_limit_is_set(store):
    set_policy(store, global_capacity=5)
    ids = [make(store, f"C{i}", policy=access(), provider=json.dumps("codex")) for i in range(5)]
    assert all(claim(store, t)["claimed"] for t in ids)


def _claim_proc(root, workspace, kind, task_id, barrier, out):
    os.environ["SOLAR_RUNTIME_ROOT"] = root
    os.environ["SOLAR_WORKSPACE"] = workspace
    solar_state.VERIFIED_PROFILES = {PROFILE: _EveryProvider()}          # a spawned process starts clean
    with solar_state.session(root, auto_backup=False) as s:
        barrier.wait()
        if kind == "manual":
            won = s.task_claim_detail(task_id, f"m-{task_id}")["claimed"]
        else:
            won = s.task_claim_next(f"w-{os.getpid()}") is not None
    out.put(bool(won))


@pytest.mark.parametrize("capacity", [1, 3, 5])
def test_simultaneous_claims_never_exceed_the_capacity(ready, tmp_path, capacity):
    with solar_state.session(ready, auto_backup=False) as s:
        set_policy(s, global_capacity=capacity)
        ids = [make(s, f"R{i}", policy=access(scopes=[f"/r/{i}"])) for i in range(8)]
    ctx = multiprocessing.get_context("spawn")
    runners = [("manual", ids[4 + i]) for i in range(4)] + [("next", None)] * 4
    barrier, out = ctx.Barrier(len(runners)), ctx.Queue()
    procs = [ctx.Process(target=_claim_proc,
                         args=(str(ready), str(tmp_path / "workspace"), kind, task_id, barrier, out))
             for kind, task_id in runners]
    for proc in procs:
        proc.start()
    won = [out.get(timeout=120) for _ in procs]
    for proc in procs:
        proc.join(30)
    with solar_state.session(ready, auto_backup=False) as s:
        assert len(active_ids(s)) == capacity == sum(won)
        assert len(s.reservations()) == capacity
        owners = [r[0] for r in s.conn.execute("SELECT task_id FROM execution_reservations")]
        assert len(set(owners)) == len(owners)                  # one owner per execution


# --------------------------------------------------------------------------
# access: readers, writers, resources, unknown tasks
# --------------------------------------------------------------------------

def test_readers_of_the_same_scope_run_together(store):
    set_policy(store, global_capacity=3)
    ids = [make(store, f"R{i}", policy=access("read", ["/repo"])) for i in range(3)]
    assert all(claim(store, t)["claimed"] for t in ids)


def test_a_writer_conflicts_with_readers_and_writers_of_its_scope(store):
    set_policy(store, global_capacity=5)
    reader = make(store, "Reader", policy=access("read", ["/repo/docs"]))
    writer = make(store, "Writer", policy=access("write", ["/repo/docs"]))
    writer2 = make(store, "Writer2", policy=access("write", ["/repo/docs"]))
    elsewhere = make(store, "Elsewhere", policy=access("write", ["/repo/src"]))
    assert claim(store, reader)["claimed"]
    assert claim(store, writer)["reason"] == "scope_conflict"
    assert claim(store, elsewhere)["claimed"]                    # disjoint scopes do not conflict
    store.task_complete(reader, token=token_of(store, reader))
    assert claim(store, writer)["claimed"]
    assert claim(store, writer2)["reason"] == "scope_conflict"


@pytest.mark.parametrize("held,asked", [("/repo", "/repo/docs/a.md"), ("/repo/docs/a.md", "/repo"),
                                        ("/repo/docs", "/repo/docs/")])
def test_parent_and_child_scopes_overlap(store, held, asked):
    set_policy(store, global_capacity=3)
    first = make(store, "First", policy=access("write", [held]))
    second = make(store, "Second", policy=access("read", [asked]))
    assert claim(store, first)["claimed"]
    assert claim(store, second)["reason"] == "scope_conflict"


def test_a_sibling_with_a_common_prefix_is_not_a_child(store):
    set_policy(store, global_capacity=3)
    first = make(store, "First", policy=access("write", ["/repo/doc"]))
    second = make(store, "Second", policy=access("write", ["/repo/docs"]))
    assert claim(store, first)["claimed"] and claim(store, second)["claimed"]


def test_a_symlink_alias_is_the_same_scope(store, tmp_path):
    real = tmp_path / "project"
    (real / "src").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    set_policy(store, global_capacity=3)
    writer = make(store, "Writer", policy=access("write", [str(real)]))
    reader = make(store, "Reader", policy=access("read", [str(alias / "src")]))
    assert claim(store, writer)["claimed"]
    assert claim(store, reader)["reason"] == "scope_conflict"


def test_a_resource_is_held_exclusively(store):
    set_policy(store, global_capacity=3)
    one = make(store, "One", policy=access("read", ["/a"], ["browser"]))
    two = make(store, "Two", policy=access("read", ["/b"], ["browser"]))
    three = make(store, "Three", policy=access("read", ["/c"], ["other"]))
    assert claim(store, one)["claimed"]
    assert claim(store, two)["reason"] == "resource:browser"
    assert claim(store, three)["claimed"]


def test_the_resources_of_the_hooks_count_too(store):
    set_policy(store, global_capacity=3)
    one = make(store, "One", policy=access("read", ["/a"]), resources=json.dumps("browser"))
    two = make(store, "Two", policy=access("read", ["/b"], ["browser"]))
    assert claim(store, one)["claimed"]
    assert claim(store, two)["reason"] == "resource:browser"


def test_a_task_that_declares_nothing_runs_alone(store):
    set_policy(store, global_capacity=3)
    legacy, reader = make(store, "Legacy"), make(store, "Reader", policy=access())
    token = claim(store, reader)["token"]
    assert claim(store, legacy)["reason"] == "exclusive_needs_idle"      # it needs the machine idle
    store.task_complete(reader, token=token)
    assert claim(store, legacy)["claimed"]
    assert store.reservation_for(legacy)["access_class"] == "exclusive"
    late = make(store, "Late", policy=access())
    assert claim(store, late)["reason"] == "blocked_by_exclusive"        # and blocks the others
    assert store.task_claim_next("w") is None


def test_an_invalid_declaration_cannot_be_approved(store):
    task = make(store, "Bad", policy="{not json", status="draft")
    with pytest.raises(solar_state.FormatError):
        store.task_approve(task)
    assert store.task_status(task) == "draft" and store.reservations() == []


@pytest.mark.parametrize("value", [
    '{"version":1,"mode":"read","scopes":["relative/path"]}',
    '{"version":1,"mode":"write","scopes":[]}',
    '{"version":1,"mode":"delete","scopes":["/a"]}',
    '{"version":2,"mode":"read","scopes":["/a"]}',
    '{"version":1,"mode":"read","scopes":["/a"],"other":1}',
    '{"version":1,"mode":"read","scopes":["/a"],"resources":["bad name"]}',
    '["read"]',
])
def test_access_declarations_are_validated(value):
    with pytest.raises(solar_state.FormatError):
        solar_state.parse_access_policy(value)


def test_the_declaration_is_canonical():
    a = solar_state.canonical_policy_text(
        "access_policy", '{"version":1,"mode":"read","scopes":["/b/../a","/a","/c/"],"resources":["z","y"]}')
    b = solar_state.canonical_policy_text(
        "access_policy", '{ "resources": ["y","z"], "scopes": ["/c", "/a"], "mode": "read", "version": 1 }')
    assert a == b == '{"mode":"read","resources":["y","z"],"scopes":["/a","/c"],"version":1}'


# --------------------------------------------------------------------------
# revalidation at the claim
# --------------------------------------------------------------------------

def test_dependencies_cancellation_and_approval_are_revalidated_by_both_claims(store):
    set_policy(store, global_capacity=5)
    first = make(store, "First", policy=access())
    waits = make(store, "Waits", policy=access(), blocked_by_task_ids=json.dumps(first))
    assert claim(store, waits)["reason"] == "blocked_by_dependency"
    assert store.task_claim_next("w")["id"] == first
    stopped = make(store, "Stopped", policy=access())
    store.cancellation_request(stopped)
    assert claim(store, stopped)["reason"] == "cancellation_requested"
    unapproved = make(store, "Unapproved", policy=access(), status="draft")
    store.conn.execute("UPDATE tasks SET status = 'queued' WHERE id = ?", (unapproved,))
    assert claim(store, unapproved)["reason"] == "absent"
    assert store.task_claim_next("w") is None
    assert store.task_status(waits) == "queued"          # a refusal moves nothing


def test_a_task_without_approval_takes_no_place(store):
    task = make(store, "Loose", policy=access(), status="draft")
    store.conn.execute("UPDATE tasks SET status = 'queued' WHERE id = ?", (task,))
    assert claim(store, task)["claimed"] is False
    assert store.reservations() == []


def test_a_refused_claim_does_not_consume_the_recurring_interval(store):
    set_policy(store)
    held = make(store, "Held", policy=access())
    claim(store, held)
    recurring = make(store, "Tick", policy=access(), recurring="true", recurring_min_interval="3600")
    refused = store.task_claim_detail(recurring, "w", stamp_last_run=True)
    assert refused["reason"] == "global_capacity"
    assert store.task_field(recurring, "recurring_last_run") is None
    store.task_complete(held, token=token_of(store, held))
    won = store.task_claim_detail(recurring, "w", stamp_last_run=True)
    assert won["claimed"] and store.task_field(recurring, "recurring_last_run")


def test_a_recurring_task_never_runs_twice_at_once(store):
    set_policy(store, global_capacity=3)
    tick = make(store, "Tick", policy=access(), recurring="true", recurring_min_interval="1")
    assert claim(store, tick)["claimed"]
    assert claim(store, tick)["reason"] == "not_queued"
    assert store.task_claim_next("w") is None
    assert len(store.reservations()) == 1


# --------------------------------------------------------------------------
# drain barrier for exclusive tasks
# --------------------------------------------------------------------------

def _age_wait(store, task_id, seconds):
    then = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.conn.execute("UPDATE claim_waits SET first_blocked_at = ? WHERE task_id = ?", (then, task_id))


def test_a_stream_of_readers_cannot_starve_an_exclusive_task(store):
    set_policy(store, global_capacity=3, exclusive_wait_seconds=30)
    r1 = make(store, "R1", policy=access("read", ["/a"]))
    t1 = claim(store, r1)["token"]
    exclusive = make(store, "Exclusive")
    assert claim(store, exclusive)["reason"] == "exclusive_needs_idle"       # the clock starts
    r2 = make(store, "R2", policy=access("read", ["/a"]))
    assert claim(store, r2)["claimed"]                                       # still admitted: it has not waited long
    _age_wait(store, exclusive, 31)
    r3 = make(store, "R3", policy=access("read", ["/a"]))
    assert claim(store, r3)["reason"] == "drain_barrier"                     # the line is closed
    assert store.task_claim_next("w") is None
    assert store.audit_rows("exclusive_drain_started")[0]["task_id"] == exclusive
    assert len(store.audit_rows("exclusive_drain_started")) == 1
    store.task_complete(r1, token=t1)
    store.task_complete(r2, token=token_of(store, r2))
    assert store.task_claim_next("w")["id"] == exclusive                     # before any reader comes back
    assert claim(store, r3)["reason"] == "blocked_by_exclusive"


def test_only_an_eligible_exclusive_closes_the_line(store):
    set_policy(store, global_capacity=3, exclusive_wait_seconds=30)
    held = make(store, "Held", policy=access())
    claim(store, held)
    dependency = make(store, "Dependency", policy=access(), status="draft")
    waiting = make(store, "Waiting", status="draft",                         # exclusive, but it waits on a dependency
                   blocked_by_task_ids=json.dumps(dependency))
    store.task_approve(waiting)
    store.conn.execute("INSERT INTO claim_waits (task_id, first_blocked_at) VALUES (?, '2000-01-01T00:00:00Z')",
                       (waiting,))
    other = make(store, "Other", policy=access())
    assert claim(store, other)["claimed"]                                    # no barrier from an ineligible task


def test_the_oldest_eligible_exclusive_goes_first(store):
    set_policy(store, global_capacity=3, exclusive_wait_seconds=30)
    held = make(store, "Held", policy=access())
    token = claim(store, held)["token"]
    low = make(store, "Low", priority="low")
    high = make(store, "High", priority="high")
    for task in (low, high):
        claim(store, task)
        _age_wait(store, task, 60)
    store.task_complete(held, token=token)
    assert store.task_claim_next("w")["id"] == high


# --------------------------------------------------------------------------
# the configuration revision
# --------------------------------------------------------------------------

def test_an_invalid_revision_is_refused_and_the_applied_one_stays(store):
    set_policy(store, global_capacity=3)
    before = store.async_policy()
    for bad in (dict(global_capacity=6), dict(global_capacity=0), dict(global_capacity=True),
                dict(global_capacity=2, revision=before["revision"]),          # not above the applied one
                dict(provider_capacity={"codex": 9}), dict(provider_capacity=[1]),
                dict(exclusive_wait_seconds=0), dict(enabled_reader_profiles="x"),
                dict(schema_version=2), dict(unknown=1)):
        document = dict(schema_version=1, revision=before["revision"] + 1, global_capacity=2)
        document.update(bad)
        with pytest.raises(PolicyInvalid):
            store.async_policy_apply(document, actor="t")
    with pytest.raises(PolicyInvalid):
        store.async_policy_apply("not an object")
    assert store.async_policy() == before
    ids = [make(store, f"R{i}", policy=access()) for i in range(4)]
    assert [claim(store, t)["claimed"] for t in ids] == [True, True, True, False]   # still capacity 3


def test_the_file_proposes_and_only_an_applied_revision_counts(store):
    path = solar_state.config_path(store.root)
    assert path == store.root / "async-tasks" / "config" / "async-execution.json"
    solar_state.write_proposal(dict(schema_version=1, revision=1, global_capacity=5,
                                    enabled_reader_profiles=[PROFILE]), store.root)
    status = store.async_policy_status()
    assert status["pending"] and status["applies"] and status["applied"]["global_capacity"] == 1
    ids = [make(store, f"R{i}", policy=access()) for i in range(2)]
    assert claim(store, ids[0])["claimed"] and claim(store, ids[1])["reason"] == "exclusive_needs_idle"
    store.task_complete(ids[0], token=token_of(store, ids[0]))               # it ran alone: no profile was enabled yet
    digest = status["proposal"]["digest"]
    with pytest.raises(PolicyInvalid, match="digest"):
        store.async_policy_apply(solar_state.read_proposal(store.root)["document"], expected_digest="0" * 64)
    applied = store.async_policy_apply(solar_state.read_proposal(store.root)["document"],
                                       actor="t", expected_digest=digest)
    assert applied["global_capacity"] == 5 and applied["revision"] == 1
    assert store.async_policy_status()["pending"] is False
    assert claim(store, ids[1])["claimed"]


def test_a_broken_file_changes_nothing(store):
    path = solar_state.config_path(store.root)
    path.parent.mkdir(parents=True)
    path.write_text("{ nope", encoding="utf-8")
    status = store.async_policy_status()
    assert status["proposal"]["error"] and status["applies"] is False
    with pytest.raises(PolicyInvalid):
        store.async_policy_apply(solar_state.read_proposal(store.root)["document"])
    assert store.async_policy()["global_capacity"] == 1


def test_applying_is_audited(store):
    set_policy(store, global_capacity=2)
    event = store.audit_rows("async_policy_applied")[-1]
    assert (event["revision"], event["previous_revision"], event["global_capacity"]) == (1, 0, 2)


# --------------------------------------------------------------------------
# maintenance barrier
# --------------------------------------------------------------------------

def test_a_maintenance_barrier_stops_every_claim(store):
    a, b = make(store, "A", policy=access()), make(store, "B", policy=access())
    solar_state.maintenance_path(store.root).write_text(json.dumps(dict(operation="update")))
    assert claim(store, a) == dict(claimed=False, reason="maintenance")
    assert store.task_claim_next("w") is None
    with pytest.raises(TransitionRefused, match="maintenance"):
        store.task_transition(b, "active")
    solar_state.maintenance_path(store.root).write_text("{broken")           # unreadable: closed, not open
    assert claim(store, a)["reason"] == "maintenance"
    solar_state.maintenance_path(store.root).unlink()
    assert claim(store, a)["claimed"]


# --------------------------------------------------------------------------
# material keys of the approval
# --------------------------------------------------------------------------

OLD_KEYS = ("object", "scope", "effect", "priority", "provider", "planet", "agent",
            "responsibility", "agent_contract", "notify_when", "origin_channel", "origin_chat_id",
            "resources", "cleanup_required", "cleanup_timeout", "scheduled_time",
            "scheduled_weekdays", "scheduled_timezone", "recurring", "recurring_min_interval",
            "recurring_max_runs", "executor", "local_command", "local_timeout")


def _digest_before_this_contract(pairs, definition):
    material = {key: solar_state.value_of(solar_state._get_pair(pairs, key)) for key in OLD_KEYS}
    payload = json.dumps(dict(fields=material, definition=definition), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return "v2:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_a_task_that_declares_none_of_the_new_keys_keeps_its_digest(store):
    """The approvals standing today stay valid: the digest version did not change."""
    task = make(store, "Old", priority="high", scope=json.dumps("one file"))
    task_row = store.task_get(task)
    expected = _digest_before_this_contract(task_row["frontmatter"], "# Old\n\nDo Old.".split("\n", 1)[1].strip())
    stored = solar_state.value_of(solar_state._get_pair(task_row["frontmatter"], "approved_digest"))
    assert stored == expected and solar_state.DIGEST_PREFIX == "v2:"
    assert claim(store, task)["claimed"]


@pytest.mark.parametrize("key,first,second", [
    ("access_policy", access("read", ["/a"]), access("write", ["/a"])),
    ("subtask_policy", None, None),
    ("execution_profile", "text_only_review_v1", "other_profile"),
    ("review_input_digest", "a" * 64, "b" * 64),
    ("review_input_manifest", "manifests/1.json", "manifests/2.json"),
])
@pytest.mark.parametrize("entry", ["claim", "claim_next"])
def test_changing_a_new_material_key_voids_the_approval(store, key, first, second, entry):
    if key == "subtask_policy":
        first = _subtask_policy("one")
        second = _subtask_policy("two")
    task = make(store, "Tracked", **{key: first})
    store.task_set(task, key, second)                    # an edit that did not go through an approval
    if entry == "claim":
        assert claim(store, task) == dict(claimed=False, reason="mismatch")
    else:
        assert store.task_claim_next("w") is None
    assert store.task_status(task) == "queued"


@pytest.mark.parametrize("key,value", [("access_policy", access("read", ["/a"])),
                                       ("execution_profile", "text_only_review_v1"),
                                       ("review_input_digest", "c" * 64),
                                       ("review_input_manifest", "m.json")])
def test_adding_a_new_key_to_an_approved_task_voids_the_approval(store, key, value):
    task = make(store, "Plain")
    store.task_set(task, key, value)
    assert claim(store, task)["reason"] == "mismatch"


def test_a_queued_edit_of_a_new_key_goes_back_to_draft(store):
    task = make(store, "Edit", policy=access("read", ["/a"]))
    row = store.task_get(task)
    out = store.task_update(task, expected_row_version=row["row_version"], allowed_status=("queued",),
                            fields={"access_policy": access("write", ["/a"])})
    assert out["status"] == "draft" and out["approval_withdrawn"] is True


def test_the_policies_are_hashed_in_canonical_form():
    base = [["title", ' "T"'], ["priority", " normal"]]

    def digest(value):
        return solar_state.material_digest(base + [["access_policy", " " + value]], "", definition="x")
    one = digest('{"version":1,"mode":"read","scopes":["/b","/a"],"resources":[]}')
    two = digest('{"resources":[],"scopes":["/a","/b/"],"mode":"read","version":1}')
    assert one == two
    assert one != digest('{"version":1,"mode":"write","scopes":["/b","/a"],"resources":[]}')
    assert digest("{not json") not in (one, two)        # an invalid value is still hashed, as written


def _subtask_policy(label):
    return json.dumps(dict(
        version=1, max_children=3, providers=["claude"],
        templates=[dict(key=f"review-{label}", title="Review", instructions="Review the evidence.")],
        object="the plan", scope="one file", effect="text only",
        max_access=json.loads(access("read", ["/e"]))), sort_keys=True)


def test_subtask_policy_is_validated_and_canonical():
    text = solar_state.canonical_policy_text("subtask_policy", _subtask_policy("a"))
    assert json.loads(text)["max_children"] == 3 and text == solar_state.canonical_policy_text(
        "subtask_policy", json.dumps(json.loads(text), indent=2))
    for broken in ({"max_children": 6}, {"providers": []}, {"templates": []}, {"max_access": None},
                   {"extra": 1}, {"object": ""}):
        document = json.loads(_subtask_policy("a"))
        document.update(broken)
        with pytest.raises(solar_state.FormatError):
            solar_state.parse_subtask_policy(document)


def test_an_approval_with_an_invalid_new_key_is_refused(store):
    cases = [("subtask_policy", "{}"), ("execution_profile", "no spaces allowed"),
             ("review_input_digest", "xyz"), ("review_input_manifest", '""')]
    for key, value in cases:
        task = make(store, f"Bad {key}", status="draft", **{key: value})
        with pytest.raises(solar_state.FormatError):
            store.task_approve(task)
        assert store.task_status(task) == "draft"


# --------------------------------------------------------------------------
# provenance and legacy children
# --------------------------------------------------------------------------

def test_a_derived_authorization_is_recorded_once_and_checked_at_the_claim(store):
    set_policy(store, global_capacity=3)
    parent = make(store, "Parent", policy=access())
    child = make(store, "Child", policy=access())
    assert store.authorization_record(child, parent, "k1", parent_digest="p", manifest_digest="m")
    assert store.authorization_record(child, parent, "k1", parent_digest="p", manifest_digest="m") is False
    with pytest.raises(solar_state.StateError):
        store.authorization_record(child, parent, "k1", parent_digest="p", manifest_digest="other")
    assert claim(store, child)["claimed"] is True        # the parent still stands (queued)


@pytest.mark.parametrize("revoke", ["cancel_request", "draft", "cancelled"])
def test_a_revoked_parent_stops_new_derived_claims(store, revoke):
    parent = make(store, "Parent", policy=access())
    child = make(store, "Child", policy=access())
    store.authorization_record(child, parent, "k1", parent_digest="p", manifest_digest="m")
    if revoke == "cancel_request":
        store.cancellation_request(parent)
    elif revoke == "draft":
        store.task_return_to_draft(parent, expected_row_version=store.task_get(parent)["row_version"])
    else:
        store.task_cancel(parent)
    assert claim(store, child) == dict(claimed=False, reason="parent_revoked")
    assert store.task_claim_next("w") is None


def test_legacy_children_are_listed_and_never_backfilled(store):
    parent = make(store, "Parent", policy=access())
    ok = make(store, "Ok child", policy=access(), parent_task_id=json.dumps(parent))
    stale = make(store, "Stale child", policy=access(), parent_task_id=json.dumps(parent))
    store.task_set_body(stale, store.task_get(stale)["body"].replace("Do Stale child.", "Do something else."))
    derived = make(store, "Derived child", policy=access(), parent_task_id=json.dumps(parent))
    store.authorization_record(derived, parent, "k", parent_digest="p", manifest_digest="m")
    found = {c["id"]: c for c in store.legacy_children()}
    assert set(found) == {ok, stale} and derived not in found
    assert found[ok]["executable"] is True and found[stale]["approval"] == "mismatch"
    assert found[stale]["executable"] is False
    assert store.conn.execute("SELECT COUNT(*) FROM task_authorizations").fetchone()[0] == 1
    assert claim(store, stale)["claimed"] is False


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cli(root, *args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=60, env={**os.environ, **(env or {})})


def test_the_cli_hands_out_and_demands_the_token(ready):
    with solar_state.session(ready, auto_backup=False) as s:
        a = make(s, "A", policy=access())
    claimed = cli(ready, "task", "claim", a, "--worker", "bash")
    assert claimed.returncode == 0, claimed.stderr
    token = json.loads(claimed.stdout)["token"]
    refused = cli(ready, "task", "complete", a)
    assert refused.returncode == 2 and "StaleToken" in refused.stderr
    assert cli(ready, "task", "complete", a, "--token", "0" * 32).returncode == 2
    assert cli(ready, "task", "complete", a, env={"SOLAR_TASK_TOKEN": token}).returncode == 0


def test_the_cli_claim_next_reports_the_token_and_what_waits(ready):
    with solar_state.session(ready, auto_backup=False) as s:
        set_policy(s)
        make(s, "A", policy=access())
        make(s, "B", policy=access())
    out = json.loads(cli(ready, "task", "claim-next", "--worker", "w").stdout)
    assert out["claimed"] and out["token"] and out["waiting"] == []
    again = json.loads(cli(ready, "task", "claim-next", "--worker", "w").stdout)
    assert again["claimed"] is False and again["waiting"] == [dict(id="b", reason="exclusive_needs_idle")]
    listed = json.loads(cli(ready, "task", "reservations").stdout)
    assert [r["task_id"] for r in listed] == ["a"]


def test_the_cli_applies_the_proposal_file(ready):
    with solar_state.session(ready, auto_backup=False):
        pass
    solar_state.write_proposal(dict(schema_version=1, revision=1, global_capacity=3), ready)
    status = json.loads(cli(ready, "async-policy", "status").stdout)
    assert status["pending"] is True
    applied = cli(ready, "async-policy", "apply", "--digest", status["proposal"]["digest"])
    assert applied.returncode == 0, applied.stderr
    assert json.loads(cli(ready, "async-policy", "status").stdout)["applied"]["global_capacity"] == 3
    rejected = cli(ready, "async-policy", "apply")                    # same revision again
    assert rejected.returncode == 2 and "PolicyInvalid" in rejected.stderr
    assert json.loads(cli(ready, "maintenance").stdout)["held"] is False


# --------------------------------------------------------------------------
# a declaration is trusted only for an enabled execution profile
# --------------------------------------------------------------------------

def test_a_declaration_alone_never_makes_a_task_concurrent(store):
    """The providers run with their own permissions: `read` does not stop a write."""
    set_policy(store, global_capacity=5, enabled_reader_profiles=[])          # nothing is enabled yet
    codex = [make(store, f"C{i}", policy=access("read", [f"/r/{i}"]), profile=None, provider=json.dumps("codex"))
             for i in range(2)]
    assert claim(store, codex[0])["claimed"]
    assert claim(store, codex[1])["reason"] == "exclusive_needs_idle"
    assert store.reservation_for(codex[0])["access_class"] == "exclusive"
    assert store.task_claim_next("w") is None


def test_a_declaration_with_a_profile_that_is_not_enabled_serializes(store):
    set_policy(store, global_capacity=5, enabled_reader_profiles=[])
    first = make(store, "First", policy=access("read", ["/a"]))
    second = make(store, "Second", policy=access("read", ["/b"]))
    assert claim(store, first)["claimed"] and claim(store, second)["reason"] == "exclusive_needs_idle"
    store.task_complete(first, token=token_of(store, first))
    other = make(store, "Other", policy=access("read", ["/c"]), profile="some_other_profile")
    set_policy(store, enabled_reader_profiles=[PROFILE])
    assert claim(store, other)["claimed"]
    assert claim(store, second)["reason"] == "blocked_by_exclusive"            # still not the enabled one


def test_writers_with_disjoint_scopes_also_wait_for_an_enabled_profile(store):
    set_policy(store, global_capacity=5, enabled_reader_profiles=[])
    one = make(store, "One", policy=access("write", ["/repo/a"]))
    two = make(store, "Two", policy=access("write", ["/repo/b"]))
    assert claim(store, one)["claimed"] and claim(store, two)["reason"] == "exclusive_needs_idle"


def test_an_enabled_profile_lets_declared_tasks_run_together(store):
    set_policy(store, global_capacity=3, enabled_reader_profiles=[PROFILE])
    ids = [make(store, f"R{i}", policy=access("read", [f"/r/{i}"])) for i in range(3)]
    assert all(claim(store, t)["claimed"] for t in ids)
    assert {r["access_class"] for r in store.reservations()} == {"declared"}


def test_enabling_a_profile_nobody_implements_grants_no_concurrency(store, monkeypatch):
    """Listing the name in the policy is not enough: with no verified implementation for the
    provider, the tasks keep running alone (this is the state until the profile is delivered)."""
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {})
    set_policy(store, global_capacity=5, enabled_reader_profiles=[PROFILE])
    ids = [make(store, f"V{i}", policy=access("read", [f"/v/{i}"]), provider=json.dumps("codex"))
           for i in range(2)]
    assert claim(store, ids[0])["claimed"]
    assert claim(store, ids[1])["reason"] == "exclusive_needs_idle"
    assert store.reservation_for(ids[0])["access_class"] == "exclusive"
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {PROFILE: frozenset({"claude"})})
    other = make(store, "Other", policy=access("read", ["/v/9"]), provider=json.dumps("codex"))
    assert claim(store, other)["reason"] == "exclusive_needs_idle"            # verified for claude only


def test_a_queued_task_that_is_cancelled_leaves_no_wait_behind(store):
    set_policy(store, global_capacity=1)
    running = make(store, "Running")
    waiting = make(store, "Waiting")
    assert claim(store, running)["claimed"]
    assert claim(store, waiting)["claimed"] is False
    assert store.conn.execute("SELECT 1 FROM claim_waits WHERE task_id = ?", (waiting,)).fetchone()
    store.task_cancel(waiting)
    assert store.conn.execute("SELECT 1 FROM claim_waits WHERE task_id = ?", (waiting,)).fetchone() is None


def test_disabling_the_profile_makes_new_starts_exclusive_again(store):
    set_policy(store, global_capacity=3)
    first = make(store, "First", policy=access("read", ["/a"]))
    second = make(store, "Second", policy=access("read", ["/b"]))
    assert claim(store, first)["claimed"]
    set_policy(store, enabled_reader_profiles=[])
    assert claim(store, second)["reason"] == "exclusive_needs_idle"            # and the running one is untouched
    assert store.task_status(first) == "active"


def test_provider_limits_are_matched_in_lowercase(store):
    set_policy(store, global_capacity=5, provider_capacity={"Codex": 1})
    assert store.async_policy()["provider_capacity"] == {"codex": 1}
    a = make(store, "A", policy=access("read", ["/a"]), provider=json.dumps("Codex"))
    b = make(store, "B", policy=access("read", ["/b"]), provider=json.dumps("codex"))
    assert claim(store, a)["claimed"] and claim(store, b)["reason"] == "provider_capacity"
    with pytest.raises(PolicyInvalid, match="twice"):
        set_policy(store, provider_capacity={"Codex": 1, "codex": 2})


# --------------------------------------------------------------------------
# tokens of executions that ended
# --------------------------------------------------------------------------

def test_the_token_of_a_finished_execution_cannot_fail_the_next_run(store):
    set_policy(store)
    tick = make(store, "Tick", policy=access("read", ["/a"]), recurring="true", recurring_min_interval="1")
    old = claim(store, tick)["token"]
    assert store.task_complete(tick, token=old) == "queued"                   # back in the queue for its next run
    with pytest.raises(StaleToken):
        store.task_fail(tick, "late failure", token=old)
    assert store.task_status(tick) == "queued"
    done = make(store, "Done", policy=access("read", ["/b"]))
    token = claim(store, done)["token"]
    store.task_complete(done, token=token)
    with pytest.raises(StaleToken):
        store.task_fail(done, "late failure", token=token)
    assert store.task_status(done) == "completed"
    store.task_fail(tick, "operator note")                                    # no token, no execution claimed


# --------------------------------------------------------------------------
# a process that cannot be shown to be gone is not gone
# --------------------------------------------------------------------------

def _expired_owner(store, pid):
    a = make(store, "A", policy=access())
    token = claim(store, a)["token"]
    store.reservation_attach(a, token, pid=pid)
    store.conn.execute("UPDATE execution_reservations SET lease_expires_at = '2000-01-01T00:00:00Z'")
    return a, token


def test_the_process_table_answers_are_told_apart():
    assert solar_state._process_identity(os.getpid())
    assert solar_state._process_identity(dead_pid()) is None


@pytest.mark.parametrize("failure", ["denied", "timeout", "error_status"])
def test_a_failed_process_query_never_lets_an_owner_be_replaced(store, monkeypatch, failure):
    a, token = _expired_owner(store, os.getpid())                              # the owner is alive
    real = subprocess.run

    def broken(cmd, *args, **kwargs):
        if cmd[0] == "ps":
            if failure == "denied":
                raise PermissionError("ps: operation not permitted")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(cmd, 10)
            return subprocess.CompletedProcess(cmd, 2, "", "ps: kernel error")
        return real(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", broken)
    assert store.task_adopt(a, "w2")["reason"] == "owner_unverifiable"
    monkeypatch.undo()
    assert store.reservation_for(a)["token"] == token
    assert store.task_adopt(a, "w2", identity=lambda pid: None)["adopted"]    # proven gone: replaced


# --------------------------------------------------------------------------
# the wait clock of a task that stopped being eligible
# --------------------------------------------------------------------------

def test_a_successful_claim_still_resets_the_clock_of_an_ineligible_task(store):
    set_policy(store, global_capacity=3)
    holder = make(store, "Holder", policy=access("read", ["/a"]))
    claim(store, holder)
    waiting = make(store, "Waiting", priority="high")                         # exclusive, waits for the holder
    assert claim(store, waiting)["reason"] == "exclusive_needs_idle"
    store.task_set(waiting, "scope", json.dumps("edited"))                     # it no longer matches its approval
    assert store.conn.execute("SELECT COUNT(*) FROM claim_waits").fetchone()[0] == 1
    other = make(store, "Other", policy=access("read", ["/b"]), priority="low")
    assert store.task_claim_next("w")["id"] == other                           # a pass that claims something after it
    assert store.conn.execute("SELECT COUNT(*) FROM claim_waits").fetchone()[0] == 0


def test_tasks_a_claiming_pass_never_reached_keep_their_clock(store):
    set_policy(store, global_capacity=3)
    holder = make(store, "Holder", policy=access("read", ["/a"]))
    claim(store, holder)
    waiting = make(store, "Waiting", priority="low")
    assert claim(store, waiting)["reason"] == "exclusive_needs_idle"
    make(store, "First", policy=access("read", ["/b"]), priority="high")
    assert store.task_claim_next("w")["id"] == "first"                         # claims before reaching Waiting
    assert store.conn.execute("SELECT task_id FROM claim_waits").fetchall()[0][0] == waiting
