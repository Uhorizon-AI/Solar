"""Task edit, approve and archive in solar-state: version lock, no activation, history kept."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import solar_state
from recurring_schedule import open_now
from solar_state import TaskChanged, TransitionRefused, scheduled_now
from reservation_tokens import token_of

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
              ("scheduled_timezone", f'"{MADRID}"'), ("recurring", "true")]
    with solar_state.session() as store:
        task_id = store.task_create(fields, "\n# Weekly\n", status="queued")
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 16, 30)) is None   # 18:30 local
        claimed = store.task_claim_next("w", now=utc(2027, 4, 2, 15, 2))         # 17:02 local
        assert claimed and claimed["id"] == task_id


def test_one_off_claim_waits_until_the_nominal_time(ready):
    with solar_state.session() as store:
        task_id = make(store, status="queued", scheduled_time='"09:00"',
                       scheduled_timezone=f'"{MADRID}"', recurring="false")
        assert store.task_claim_next("w", now=utc(2026, 11, 9, 7, 45)) is None
        assert store.task_claim_next("w", now=utc(2026, 11, 9, 7, 59)) is None
        assert store.task_claim_next("w", now=utc(2026, 11, 9, 8, 0))["id"] == task_id


@pytest.mark.parametrize("recurrence", [{}, {"recurring": "false"}])
def test_legacy_one_off_claim_uses_host_time_and_waits_until_nominal(ready, recurrence):
    with solar_state.session() as store:
        task_id = make(store, status="queued", scheduled_time='"09:00"', **recurrence)
        assert store.task_claim_next("w", now=datetime(2026, 11, 9, 8, 59)) is None
        assert store.task_claim_next("w", now=datetime(2026, 11, 9, 9, 16)) is None
        assert store.task_claim_next("w", now=datetime(2026, 11, 9, 9, 15, 59))["id"] == task_id


@pytest.mark.parametrize("time,day,instant,expected", [
    ("23:55", "1", utc(2026, 11, 9, 23, 10, 59), True),  # Tuesday 00:10, Monday's window
    ("23:55", "1", utc(2026, 11, 9, 23, 11), False),
    ("00:05", "1", utc(2026, 11, 8, 23, 0), False),     # Monday before its nominal time
    ("02:30", "7", utc(2027, 3, 28, 1, 0), False),     # nonexistent local time
    ("02:30", "7", utc(2027, 10, 31, 0, 30), True),    # first fold
    ("02:30", "7", utc(2027, 10, 31, 1, 30), False),   # second fold
])
def test_one_off_eligibility_at_day_and_clock_boundaries(time, day, instant, expected):
    assert scheduled_now(time, day, instant, MADRID, recurring=False) is expected


def test_a_weekly_recurrence_is_ready_again_after_a_short_dst_week(ready):
    """Winter to summer the week is 167 hours; the schedule, not a fixed gap, decides. The field of a
    legacy task is stored and ignored."""
    fields = [("title", '"Weekly"'), ("scheduled_time", '"17:00"'), ("scheduled_weekdays", '"5"'),
              ("scheduled_timezone", f'"{MADRID}"'), ("recurring", "true"),
              ("recurring_min_interval", str(6 * 86400)),
              ("recurring_last_run", '"2027-03-26T16:05:00Z"')]
    with solar_state.session() as store:
        task_id = store.task_create(fields, "\n# Weekly\n", status="queued")
        claimed = store.task_claim_next("w", now=utc(2027, 4, 2, 15, 1))
        assert claimed and claimed["id"] == task_id


def _weekly(store, **extra):
    fields = [("title", '"Weekly"'), ("scheduled_time", '"17:00"'), ("scheduled_weekdays", '"5"'),
              ("scheduled_timezone", f'"{MADRID}"'), ("recurring", "true")] + list(extra.items())
    return store.task_create(fields, "\n# Weekly\n", status="queued")


def _finish(store, task_id, last_run):
    """The run ends: the worker stamped `last_run` at its claim and the task is queued again."""
    store.task_set(task_id, "recurring_last_run", json.dumps(last_run))
    assert store.task_complete(task_id, token=token_of(store, task_id)) == "queued"


def test_an_occurrence_that_already_ran_is_not_run_twice(ready):
    with solar_state.session() as store:
        task_id = _weekly(store)
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 14, 50))["id"] == task_id   # 16:50 local, in the window
        _finish(store, task_id, "2027-04-02T14:50:00Z")
        for minute in (51, 59):                                                           # still the same window
            assert store.task_claim_next("w", now=utc(2027, 4, 2, 14, minute)) is None
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 15, 10)) is None            # 17:10 local, same occurrence
        pairs = store.task_get(task_id)["frontmatter"]
        assert solar_state._recurring_ready(pairs, utc(2027, 4, 2, 15, 10).timestamp()) == "occurrence_already_ran"
        assert store.task_claim_next("w", now=utc(2027, 4, 9, 14, 50))["id"] == task_id   # next Friday


def test_a_run_before_the_window_does_not_count_as_the_occurrence(ready):
    with solar_state.session() as store:
        task_id = _weekly(store, recurring_last_run='"2027-04-02T10:00:00Z"')            # manual run that morning
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 15, 0))["id"] == task_id


@pytest.mark.parametrize("last,next_run", [
    ("2027-03-26T16:10:00Z", utc(2027, 4, 2, 15, 1)),
    ("2027-10-29T15:10:00Z", utc(2027, 11, 5, 16, 1)),
])
def test_the_week_of_a_clock_change_is_neither_skipped_nor_repeated(ready, last, next_run):
    """Friday 17:00 Madrid: 26 March is CET, 2 April is CEST (the week is 167 hours); 29 October 2027
    is CEST and 5 November CET (169 hours). Nothing about the gap in seconds matters."""
    with solar_state.session() as store:
        task_id = _weekly(store, recurring_last_run=json.dumps(last))
        assert store.task_claim_next("w", now=next_run)["id"] == task_id
        _finish(store, task_id, next_run.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert store.task_claim_next("w", now=next_run.replace(minute=10)) is None


def test_a_legacy_task_with_the_old_field_still_runs_by_its_schedule(ready):
    with solar_state.session() as store:
        # Its stored interval (ten days) would have blocked the next Friday; it is not read.
        task_id = _weekly(store, recurring_min_interval=str(10 * 86400),
                          recurring_last_run='"2027-03-26T16:05:00Z"')
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 15, 1))["id"] == task_id
        _finish(store, task_id, "2027-04-02T15:01:00Z")
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 15, 5)) is None             # the occurrence rule still holds


@pytest.mark.parametrize("fields", [
    [],                                                       # no schedule at all
    [("scheduled_time", '"now"')],                            # "now" is no clock time
    [("scheduled_weekdays", '"1,2,3,4,5"')],                  # weekdays without a time
])
def test_a_recurring_task_without_a_schedule_is_never_claimed(ready, fields):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"Loop"'), ("recurring", "true")] + fields, "\n# Loop\n",
                                    status="queued")
        pairs = store.task_get(task_id)["frontmatter"]
        assert solar_state._recurring_ready(pairs, utc(2027, 4, 2, 15, 1).timestamp()) == "recurring_without_schedule"
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 15, 1)) is None
        assert store.task_get(task_id)["status"] == "queued"


def _daily(store, time, tz=MADRID, **extra):
    fields = [("title", '"Daily"'), ("scheduled_time", json.dumps(time)), ("recurring", "true")]
    if tz:
        fields.append(("scheduled_timezone", json.dumps(tz)))
    return store.task_create(fields + list(extra.items()), "\n# Daily\n", status="queued")


def test_the_repeated_autumn_hour_is_one_occurrence(ready):
    """2027-10-31 02:30 Madrid happens twice: 00:15Z-00:45Z (CEST) and 01:15Z-01:45Z (CET)."""
    with solar_state.session() as store:
        task_id = _daily(store, "02:30")
        assert store.task_claim_next("w", now=utc(2027, 10, 31, 0, 20))["id"] == task_id
        _finish(store, task_id, "2027-10-31T00:20:00Z")
        assert store.task_claim_next("w", now=utc(2027, 10, 31, 1, 20)) is None
        pairs = store.task_get(task_id)["frontmatter"]
        assert solar_state._recurring_ready(pairs, utc(2027, 10, 31, 1, 20).timestamp()) == "occurrence_already_ran"


def test_the_second_pass_of_the_autumn_hour_serves_a_missed_first_one(ready):
    with solar_state.session() as store:
        task_id = _daily(store, "02:30", recurring_last_run='"2027-10-30T00:30:00Z"')
        assert store.task_claim_next("w", now=utc(2027, 10, 31, 1, 20))["id"] == task_id


@pytest.mark.parametrize("tz,time,last,first,blocked", [
    ("UTC", "00:05", "2027-11-10T00:05:00Z", utc(2027, 11, 10, 23, 55), utc(2027, 11, 11, 0, 0)),
    (MADRID, "00:10", "2027-11-09T23:10:00Z", utc(2027, 11, 10, 22, 58), utc(2027, 11, 10, 23, 0)),
])
def test_a_window_that_opens_before_midnight_belongs_to_the_next_day(ready, tz, time, last, first, blocked):
    with solar_state.session() as store:
        task_id = _daily(store, time, tz, recurring_last_run=json.dumps(last))        # already ran this morning
        assert store.task_claim_next("w", now=first)["id"] == task_id
        _finish(store, task_id, first.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert store.task_claim_next("w", now=blocked) is None


@pytest.mark.parametrize("bad", ["25:00", "12:60", "24:00", "ab:cd"])
def test_an_invalid_time_is_refused_and_does_not_block_the_next_task(ready, bad):
    now = utc(2027, 4, 2, 12, 0)
    assert solar_state.latest_recurring_occurrence(bad, None, "UTC", now.timestamp()) is None
    with solar_state.session() as store:
        broken = _daily(store, bad, "UTC")
        good = _daily(store, "12:00", "UTC")
        pairs = store.task_get(broken)["frontmatter"]
        assert solar_state._recurring_ready(pairs, now.timestamp()) == "recurring_without_schedule"
        assert store.task_claim_next("w", now=now)["id"] == good
        assert store.task_get(broken)["status"] == "queued"


def test_without_a_zone_the_host_clock_applies(ready):
    base = datetime(2027, 4, 2, 12, 0).astimezone()                                    # 12:00 on the host
    with solar_state.session() as store:
        task_id = _daily(store, "12:00", None)
        assert store.task_claim_next("w", now=base + timedelta(hours=3)) is None       # outside the window
        assert store.task_claim_next("w", now=base)["id"] == task_id                    # inside
        _finish(store, task_id, base.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert store.task_claim_next("w", now=base + timedelta(minutes=5)) is None      # same occurrence


@pytest.fixture
def madrid_host():
    """Pin the host clock to Europe/Madrid, restoring it afterwards."""
    import os
    import time
    before = os.environ.get("TZ")
    os.environ["TZ"] = MADRID
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


def test_without_a_zone_a_skipped_spring_minute_does_not_hide_the_day(ready, madrid_host):
    """Host in Madrid, 03:05 daily, no stored zone: its window opens at 02:50, a minute that does not
    exist on 2027-03-28. Sunday must still start once, not read Saturday's occurrence."""
    with solar_state.session() as store:
        task_id = _daily(store, "03:05", None, recurring_last_run='"2027-03-27T02:05:00Z"')   # Saturday 03:05 CET
        sunday = utc(2027, 3, 28, 1, 0).astimezone()                                           # 03:00 CEST, host-local like the worker's clock
        assert store.task_claim_next("w", now=sunday)["id"] == task_id
        _finish(store, task_id, "2027-03-28T01:00:00Z")
        assert store.task_claim_next("w", now=utc(2027, 3, 28, 1, 10).astimezone()) is None


def test_a_stored_unpadded_hour_is_still_read(ready):
    """A task saved as 9:00 keeps running as 09:00; only new schedules must be HH:MM."""
    with solar_state.session() as store:
        task_id = _daily(store, "9:00", "UTC")
        pairs = store.task_get(task_id)["frontmatter"]
        assert solar_state._recurring_ready(pairs, utc(2027, 4, 2, 9, 0).timestamp()) is None
        assert solar_state.latest_recurring_occurrence("9:00", None, "UTC", utc(2027, 4, 2, 9, 0).timestamp()) \
            == solar_state.latest_recurring_occurrence("09:00", None, "UTC", utc(2027, 4, 2, 9, 0).timestamp())
        assert store.task_claim_next("w", now=utc(2027, 4, 2, 9, 0))["id"] == task_id


def test_a_time_whose_whole_window_is_skipped_has_no_occurrence():
    allowed = set(range(1, 8))
    zone = ZoneInfo(MADRID)
    assert solar_state.recurring_windows(datetime(2027, 3, 28, 2, 30), zone, allowed) == []
    assert solar_state.recurring_windows(datetime(2027, 3, 28, 2, 50), zone, allowed)   # valid minutes kept


def test_the_latest_occurrence_follows_the_zone_and_the_clock_change():
    last = solar_state.latest_recurring_occurrence
    # Friday 17:00 Madrid, window opens 15 minutes earlier: 16:45 CET / CEST.
    assert last("17:00", "5", MADRID, utc(2027, 4, 2, 15, 1).timestamp()) == utc(2027, 4, 2, 14, 45).timestamp()
    assert last("17:00", "5", MADRID, utc(2027, 3, 29, 12, 0).timestamp()) == utc(2027, 3, 26, 15, 45).timestamp()
    assert last("17:00", "5", MADRID, utc(2027, 4, 2, 14, 44).timestamp()) == utc(2027, 3, 26, 15, 45).timestamp()
    assert last("17:00", "5", "Nowhere/Land", utc(2027, 4, 2, 15, 1).timestamp()) is None
    assert last("now", "5", MADRID, utc(2027, 4, 2, 15, 1).timestamp()) is None


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
        task_id = make(store, status="queued", recurring="true", **open_now())
        store.task_claim_next("w")
        store.task_complete(task_id, token=token_of(store, task_id))     # recurring: back to queued
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
        store.task_fail(failed, "boom", token=token_of(store, failed))
        version = store.task_get(failed)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_requeue(failed, expected_row_version=version + 1)
        store.task_requeue(failed, expected_row_version=version)
        assert store.task_get(failed)["status"] == "queued"
