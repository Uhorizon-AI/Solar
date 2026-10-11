"""Task edit, approve and archive in solar-state: version lock, no activation, history kept."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import solar_state
from solar_state import TaskChanged, TransitionRefused, scheduled_now

MADRID = "Europe/Madrid"


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# schedule in a named zone
# --------------------------------------------------------------------------

@pytest.mark.parametrize("instant,expected", [
    (utc(2027, 3, 26, 16, 0), True),    # Friday, CET (+01:00): 17:00 local
    (utc(2027, 4, 2, 15, 0), True),     # Friday, CEST (+02:00): 17:00 local
    (utc(2027, 4, 2, 16, 0), False),    # the winter hour again would be 18:00 local
    (utc(2027, 3, 26, 15, 0), False),   # the summer hour in winter is 16:00 local
    (utc(2027, 11, 5, 16, 10), True),   # first Friday after clocks went back
    (utc(2027, 10, 29, 15, 10), True),  # last Friday before they did
])
def test_friday_17_madrid_holds_across_clock_changes(instant, expected):
    assert scheduled_now("17:00", "5", instant, MADRID) is expected


def test_weekday_is_read_in_the_zone_not_in_utc():
    # Thursday 23:30 UTC in summer is already Friday 01:30 in Madrid.
    assert scheduled_now("01:30", "5", utc(2027, 7, 1, 23, 30), MADRID)
    assert not scheduled_now("01:30", "4", utc(2027, 7, 1, 23, 30), MADRID)


def test_an_unknown_zone_never_matches():
    for name in ("Nowhere/Land", "../etc", "Europe/../x"):
        assert not scheduled_now("17:00", "5", utc(2027, 4, 2, 15, 0), name)
        assert not scheduled_now("now", "", utc(2027, 4, 2, 15, 0), name)


def test_the_skipped_hour_of_spring_forward_is_skipped_not_guessed():
    """2027-03-28 (Sunday): 02:00-02:59 does not exist in Madrid, so 02:30 never matches."""
    day = datetime(2027, 3, 28, tzinfo=timezone.utc)
    matches = [minute for minute in range(0, 24 * 60)
               if scheduled_now("02:30", "7", day.replace(hour=minute // 60, minute=minute % 60), MADRID)]
    assert matches == []
    # The same wall time on a normal Sunday does match.
    assert scheduled_now("02:30", "7", utc(2027, 3, 21, 1, 30), MADRID)


def test_without_a_zone_the_old_behaviour_is_unchanged():
    assert scheduled_now("17:00", "5", datetime(2027, 4, 2, 17, 5))
    assert not scheduled_now("17:00", "5", datetime(2027, 4, 2, 18, 5))


def test_claim_next_reads_the_task_zone(ready):
    fields = [("title", '"Weekly"'), ("scheduled_time", '"17:00"'), ("scheduled_weekdays", '"5"'),
              ("scheduled_timezone", f'"{MADRID}"'), ("recurring", "true"),
              ("recurring_min_interval", str(6 * 86400))]
    with solar_state.session() as store:
        task_id = store.task_create(fields, "\n# Weekly\n", status="queued")
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 16, 30)) is None   # 18:30 local
        claimed = store.task_claim_next("w", now=utc(2027, 4, 2, 15, 2))         # 17:02 local
        assert claimed and claimed["id"] == task_id


def test_a_weekly_recurrence_is_ready_again_after_a_short_dst_week(ready):
    """Winter to summer the week is 167 hours; a 6-day interval still fires."""
    fields = [("title", '"Weekly"'), ("scheduled_time", '"17:00"'), ("scheduled_weekdays", '"5"'),
              ("scheduled_timezone", f'"{MADRID}"'), ("recurring", "true"),
              ("recurring_min_interval", str(6 * 86400)),
              ("recurring_last_run", '"2027-03-26T16:05:00Z"')]
    with solar_state.session() as store:
        task_id = store.task_create(fields, "\n# Weekly\n", status="queued")
        claimed = store.task_claim_next("w", now=utc(2027, 4, 2, 15, 1))
        assert claimed and claimed["id"] == task_id


# --------------------------------------------------------------------------
# edit under a version lock
# --------------------------------------------------------------------------

def make(store, status="draft", **extra):
    fields = [("title", '"T"')] + [(k, v) for k, v in extra.items()]
    return store.task_create(fields, "\n# T\n\nBody.\n", status=status)


def test_update_bumps_the_version_and_refuses_a_stale_reader(ready):
    with solar_state.session() as store:
        task_id = make(store)
        version = store.task_get(task_id)["row_version"]
        out = store.task_update(task_id, expected_row_version=version, allowed_status=("draft",),
                                fields={"object": '"o"'})
        assert out["row_version"] == version + 1 and out["status"] == "draft"
        with pytest.raises(TaskChanged):
            store.task_update(task_id, expected_row_version=version, allowed_status=("draft",),
                              fields={"object": '"p"'})
        assert store.task_get(task_id)["object"] == "o"


def test_update_never_edits_a_task_that_is_not_where_the_caller_allows(ready):
    with solar_state.session() as store:
        task_id = make(store, status="queued")
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TransitionRefused):
            store.task_update(task_id, expected_row_version=version, allowed_status=("draft", "planned"),
                              body="\n# changed\n")
        assert "changed" not in store.task_get(task_id)["body"]


def test_update_can_only_make_moves_the_table_allows(ready):
    with solar_state.session() as store:
        task_id = make(store)
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TransitionRefused):
            store.task_update(task_id, expected_row_version=version, allowed_status=("draft",),
                              to_status="active")
        assert store.task_get(task_id)["status"] == "draft"


def test_update_refuses_status_and_id_as_fields(ready):
    with solar_state.session() as store:
        task_id = make(store)
        version = store.task_get(task_id)["row_version"]
        for key in ("status", "id"):
            with pytest.raises(solar_state.StateError):
                store.task_update(task_id, expected_row_version=version, allowed_status=("draft",),
                                  fields={key: "queued"})


def _race(root, action, count=6):
    barrier = threading.Barrier(count)
    outcomes = []

    def worker(index):
        barrier.wait()
        try:
            with solar_state.session(root) as store:
                outcomes.append(action(store, index))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    return outcomes


def test_concurrent_edits_from_the_same_read_let_exactly_one_through(ready):
    with solar_state.session() as store:
        task_id = make(store)
        version = store.task_get(task_id)["row_version"]
    outcomes = _race(ready, lambda store, i: store.task_update(
        task_id, expected_row_version=version, allowed_status=("draft",),
        fields={"object": json.dumps(f"writer-{i}")}))
    wins = [o for o in outcomes if isinstance(o, dict)]
    losses = [o for o in outcomes if isinstance(o, TaskChanged)]
    assert len(wins) == 1 and len(losses) == len(outcomes) - 1
    with solar_state.session() as store:
        assert store.task_get(task_id)["row_version"] == version + 1


def test_approve_races_an_edit_and_never_queues_unseen_content(ready):
    with solar_state.session() as store:
        task_id = make(store)
        version = store.task_get(task_id)["row_version"]

    def action(store, i):
        if i % 2:
            return store.task_update(task_id, expected_row_version=version,
                                     allowed_status=("draft",), body="\n# T\n\nEdited.\n")
        return store.task_approve(task_id, expected_row_version=version)

    outcomes = _race(ready, action, count=8)
    ok = [o for o in outcomes if not isinstance(o, Exception)]
    assert len(ok) == 1
    with solar_state.session() as store:
        task = store.task_get(task_id)
    if task["status"] == "queued":
        # Approved exactly the version that was read: the edit lost.
        assert "Edited." not in task["body"]
    else:
        assert "Edited." in task["body"]


def test_approve_records_what_was_approved_and_checks_the_version(ready):
    with solar_state.session() as store:
        task_id = make(store, object='"o"', scope='"s"', effect='"e"')
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_approve(task_id, expected_row_version=version + 3)
        assert store.task_get(task_id)["status"] == "draft"
        store.task_approve(task_id, expected_row_version=version)
        task = store.task_get(task_id)
        values = {k: solar_state.value_of(v) for k, v in task["frontmatter"]}
        assert task["status"] == "queued"
        assert values["approved_digest"] == solar_state.material_digest(
            [p for p in task["frontmatter"] if not p[0].startswith("approved_")], task["body"])
        assert values["approved_row_version"] == str(version)


def test_digest_ignores_runtime_bookkeeping_but_not_content():
    base = [["title", ' "T"'], ["object", ' "o"']]
    d1 = solar_state.material_digest(base, "body")
    assert d1 == solar_state.material_digest(base + [["recurring_run_count", " 3"], ["claimed_by", " w"]], "body")
    assert d1 != solar_state.material_digest(base, "body2")
    assert d1 != solar_state.material_digest([["title", ' "T"'], ["object", ' "x"']], "body")
    assert d1 != solar_state.material_digest(base + [["scheduled_timezone", ' "UTC"']], "body")


# --------------------------------------------------------------------------
# archive keeps history
# --------------------------------------------------------------------------

def test_archive_keeps_the_row_the_body_and_every_event(ready):
    with solar_state.session() as store:
        task_id = make(store, status="queued", recurring="true")
        store.task_claim_next("w")
        store.task_complete(task_id)     # recurring: back to queued
        version = store.task_get(task_id)["row_version"]
        events_before = store.conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id = ?", (task_id,)).fetchone()[0]
        out = store.task_archive(task_id, expected_row_version=version, reason="replaced")
        task = store.task_get(task_id)
        events = store.conn.execute(
            "SELECT from_status, to_status FROM task_events WHERE task_id = ? ORDER BY seq",
            (task_id,)).fetchall()
    assert out["cancelled_first"] and out["recurring"] and task["status"] == "archived"
    assert "Body." in task["body"]
    assert len(events) == events_before + 2
    assert [tuple(e) for e in events[-2:]] == [("queued", "cancelled"), ("cancelled", "archived")]
    values = {k: solar_state.value_of(v) for k, v in task["frontmatter"]}
    assert values["archived_reason"] == "replaced" and values["archived_from"] == "queued"


def test_an_archived_recurrence_is_never_claimed_again(ready):
    with solar_state.session() as store:
        task_id = make(store, status="queued", recurring="true")
        version = store.task_get(task_id)["row_version"]
        store.task_archive(task_id, expected_row_version=version, reason="done")
        assert store.task_claim_next("w") is None


def test_archive_refuses_an_active_task(ready):
    with solar_state.session() as store:
        task_id = make(store, status="queued")
        store.task_claim_next("w")
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TransitionRefused, match="active"):
            store.task_archive(task_id, expected_row_version=version, reason="x")
        assert store.task_get(task_id)["status"] == "active"


def test_archive_refuses_to_release_a_task_that_waits_on_it(ready):
    with solar_state.session() as store:
        parent = make(store, status="queued")
        waiting = make(store, status="queued", blocked_by_task_ids=f'"{parent}"')
        version = store.task_get(parent)["row_version"]
        with pytest.raises(TransitionRefused, match=waiting):
            store.task_archive(parent, expected_row_version=version, reason="x")
        assert store.task_get(parent)["status"] == "queued"


def test_archive_refuses_while_subtasks_run(ready):
    with solar_state.session() as store:
        parent = make(store, status="queued")
        child = make(store, status="queued")
        store.task_link(parent, child)
        version = store.task_get(parent)["row_version"]
        with pytest.raises(TransitionRefused, match="subtask"):
            store.task_archive(parent, expected_row_version=version, reason="x")


def test_archive_twice_and_stale_are_refused(ready):
    with solar_state.session() as store:
        task_id = make(store)
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_archive(task_id, expected_row_version=version + 1, reason="x")
        store.task_archive(task_id, expected_row_version=version, reason="x")
        with pytest.raises(TransitionRefused, match="already"):
            store.task_archive(task_id, expected_row_version=version + 1, reason="x")


def test_a_revision_waits_for_the_task_it_replaces(ready):
    with solar_state.session() as store:
        old = make(store, status="queued", recurring="true")
        new = make(store, revises_task_id=f'"{old}"')
        version = store.task_get(new)["row_version"]
        with pytest.raises(TransitionRefused, match="can still run"):
            store.task_approve(new, expected_row_version=version)
        old_version = store.task_get(old)["row_version"]
        store.task_archive(old, expected_row_version=old_version, reason="replaced")
        store.task_approve(new, expected_row_version=version)
        assert store.task_get(new)["status"] == "queued"


def test_cancel_and_requeue_honour_an_expected_version(ready):
    with solar_state.session() as store:
        queued = make(store, status="queued")
        version = store.task_get(queued)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_cancel(queued, expected_row_version=version + 1)
        assert store.task_get(queued)["status"] == "queued"
        assert not store.cancellation_requested(queued)
        failed = make(store, status="queued")
        store.task_claim_next("w", exclude=[queued])
        store.task_fail(failed, "boom")
        version = store.task_get(failed)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_requeue(failed, expected_row_version=version + 1)
        store.task_requeue(failed, expected_row_version=version)
        assert store.task_get(failed)["status"] == "queued"
