"""A task that waits for `task.authorize_run` is written down once, can expire and is announced once.

The claim is the only place a wait is found. These tests drive it with a moment of their own (`now=`), so
nothing sleeps. Nothing here reaches a provider, a chat or a service.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import solar_state

HOUR = timedelta(hours=1)


@pytest.fixture(autouse=True)
def _default_limit(monkeypatch):
    monkeypatch.delenv(solar_state.APPROVAL_WAIT_ENV, raising=False)


class Clock:
    """The one clock of a test: the audit and the stamps read it, and so does the claim."""

    def __init__(self, monkeypatch):
        self.at = datetime.now(timezone.utc).replace(microsecond=0)
        monkeypatch.setattr(solar_state, "_now", lambda: self.at.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def advance(self, hours):
        self.at += timedelta(hours=hours)

    @property
    def local(self):
        return self.at.astimezone().replace(tzinfo=None)


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


def fm(store, task_id):
    return {k: solar_state.value_of(v) for k, v in store.task_get(task_id)["frontmatter"]}


def waiting(store, title="Work", **extra):
    """A task as the MCP flow leaves it when it is queued on the client's consent and not confined."""
    fields = [("title", json.dumps(title))] + [(k, v) for k, v in extra.items()]
    task_id = store.task_create(fields, f"\n# {title}\n\nDo it.\n")
    store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
    return task_id


def claim(store, clock=None, hours=0):
    """One claim pass. With a clock, the moment is the clock's, `hours` later."""
    if clock is not None:
        clock.advance(hours)
    return store.task_claim_next_detail("worker", now=clock.local if clock is not None else None)


def events(store, name):
    return store.audit_rows(name)


# -- the record -------------------------------------------------------------------------------------

def test_the_first_claim_that_finds_the_wait_writes_it_once(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        for _ in range(4):
            claim(store)
        rows = events(store, "awaiting_approval")
        assert len(rows) == 1
        assert rows[0]["task_id"] == task_id and rows[0]["digest"] == fm(store, task_id)["approved_digest"]
        assert rows[0]["risk"] == "high" and "Do it" not in json.dumps(rows[0])


def test_a_new_digest_is_a_new_wait(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store)
        store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                          allowed_status=("queued",), body="\n# Work\n\nDo it differently.\n")
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
        claim(store)
        assert len(events(store, "awaiting_approval")) == 2


def test_a_task_the_executor_confines_never_waits(ready, monkeypatch):
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {"repository_readonly_v1": frozenset({"codex"})})
    access = json.dumps(dict(version=1, mode="read", scopes=["/tmp/repo"], resources=[]), sort_keys=True,
                        separators=(",", ":"))
    with solar_state.session() as store:
        task_id = waiting(store, provider="codex", execution_profile="repository_readonly_v1",
                          access_policy=access)
        assert claim(store)["task"]["id"] == task_id
        assert events(store, "awaiting_approval") == []


def test_the_wait_reports_since_and_when_it_ends(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store)
        item = next(w for w in store.queue_waits() if w["id"] == task_id)
        assert item["reason"] == "awaiting_approval"
        assert item["since"] == events(store, "awaiting_approval")[0]["ts"]
        assert datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00")) - \
            datetime.fromisoformat(item["since"].replace("Z", "+00:00")) == 72 * HOUR
        assert store.approval_wait(task_id)["since"] == item["since"]


def test_before_any_claim_the_wait_dates_from_the_approval(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        assert store.approval_wait(task_id)["since"] == fm(store, task_id)["approved_at"]


# -- the limit --------------------------------------------------------------------------------------

def test_a_one_off_task_goes_back_to_draft_when_the_wait_ends(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        claim(store, clock, 71)
        assert store.task_status(task_id) == "queued"
        claim(store, clock, 2)
        assert store.task_status(task_id) == "draft"
        assert "approved_digest" not in fm(store, task_id) and "approved_consent" not in fm(store, task_id)
        ended = events(store, "approval_wait_expired")
        assert len(ended) == 1 and ended[0]["outcome"] == "returned_to_draft"
        assert events(store, "task_approval_withdrawn")[-1]["reason"] == "approval_wait_expired"
        assert claim(store, clock, 10)["task"] is None      # and it cannot run


def test_a_recurring_task_loses_only_that_occurrence(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store, recurring="true", recurring_min_interval="3600", scheduled_time="now")
        before = fm(store, task_id)
        claim(store, clock)
        claim(store, clock, 73)
        after = fm(store, task_id)
        assert store.task_status(task_id) == "queued"                       # kept in the queue
        assert after["approved_digest"] == before["approved_digest"]       # approval kept
        assert after["recurring"] == "true" and after["scheduled_time"] == "now"
        assert after["recurring_last_run"]                                 # this occurrence is spent
        assert "run_authorized_digest" not in after                        # nothing was authorized
        assert events(store, "approval_wait_expired")[0]["outcome"] == "occurrence_skipped"
        # nothing runs, and nothing is owed: the next occurrence starts a wait of its own
        assert claim(store, clock, 2)["task"] is None
        assert len(events(store, "awaiting_approval")) == 2
        assert len(events(store, "approval_wait_expired")) == 1
        # authorizing the new wait lets exactly the next occurrence run
        store.task_authorize_run(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert claim(store, clock)["task"]["id"] == task_id


def test_the_skipped_occurrence_is_not_run_later_in_a_burst(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store, recurring="true", recurring_min_interval="86400")
        claim(store, clock)
        claim(store, clock, 73)
        store.task_authorize_run(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        # authorized at once, yet the interval since the skipped occurrence has not passed: no catch-up
        assert claim(store, clock, 1)["task"] is None
        assert claim(store, clock, 24)["task"]["id"] == task_id


def test_authorizing_in_time_ends_the_wait_for_good(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        store.task_authorize_run(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert claim(store, clock, 200)["task"]["id"] == task_id
        assert events(store, "approval_wait_expired") == []


@pytest.mark.parametrize("value,hours", [("1", 1), ("0.5", 0.5), ("", 72), ("junk", 72), ("nan", 72)])
def test_the_limit_is_configurable(ready, monkeypatch, value, hours):
    monkeypatch.setenv(solar_state.APPROVAL_WAIT_ENV, value)
    assert solar_state.approval_wait_limit() == hours * 3600


@pytest.mark.parametrize("value", ["0", "-3", "inf"])
def test_a_limit_of_zero_turns_the_expiry_off(ready, clock, monkeypatch, value):
    monkeypatch.setenv(solar_state.APPROVAL_WAIT_ENV, value)
    assert solar_state.approval_wait_limit() is None
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        claim(store, clock, 5000)
        assert store.task_status(task_id) == "queued"
        assert store.approval_wait(task_id)["expires_at"] is None


def test_a_shorter_limit_applies(ready, clock, monkeypatch):
    monkeypatch.setenv(solar_state.APPROVAL_WAIT_ENV, "2")
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        claim(store, clock, 1)
        assert store.task_status(task_id) == "queued"
        claim(store, clock, 2)
        assert store.task_status(task_id) == "draft"


def test_reading_the_queue_never_ends_a_wait(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        clock.advance(500)
        store.queue_waits(now=clock.local)
        assert store.task_status(task_id) == "queued" and events(store, "approval_wait_expired") == []


# -- the notice -------------------------------------------------------------------------------------

def test_each_wait_and_each_ending_is_announced_once(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        pending = store.approval_notices()
        assert [p["event"] for p in pending] == ["awaiting_approval"]
        taken = store.approval_notice_claim(pending[0]["ref"])
        assert taken == dict(task_id=task_id, kind="waiting", title="Work", outcome=None)
        assert store.approval_notice_claim(pending[0]["ref"]) is None          # taken: not twice
        assert store.approval_notices() == []
        claim(store, clock)
        claim(store, clock)
        assert store.approval_notices() == []                                  # polling adds nothing
        claim(store, clock, 73)
        ended = store.approval_notices()
        assert [p["event"] for p in ended] == ["approval_wait_expired"]
        again = store.approval_notice_claim(ended[0]["ref"])
        assert again["kind"] == "expired" and again["outcome"] == "returned_to_draft"


def test_a_wait_that_is_already_over_is_not_announced(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store)
        store.task_authorize_run(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        ref = store.approval_notices()[0]["ref"]
        assert store.approval_notice_claim(ref) is None
        assert store.approval_notices() == []
        assert events(store, "approval_notice")[0]["skipped"] is True
        assert events(store, "approval_notice_result") == []                  # nothing was sent, nothing to report


def test_the_notice_rows_carry_no_instructions(ready):
    with solar_state.session() as store:
        waiting(store)
        claim(store)
        ref = store.approval_notices()[0]["ref"]
        store.approval_notice_claim(ref)
        store.approval_notice_result(ref, True)
        text = "".join(store.audit_lines())
        assert "Do it." not in text
        assert all("title" not in row for row in events(store, "approval_notice"))


def test_a_notice_for_content_that_has_since_changed_is_not_sent(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store)
        old = store.approval_notices()[0]["ref"]
        store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                          allowed_status=("queued",), body="\n# Work\n\nDo it differently.\n")
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
        claim(store)
        assert store.approval_notice_claim(old) is None                       # the content it named is gone
        fresh = [n for n in store.approval_notices() if n["ref"] != old]
        assert len(fresh) == 1 and store.approval_notice_claim(fresh[0]["ref"])["kind"] == "waiting"


def test_approving_the_same_content_again_after_the_wait_ended_starts_a_new_wait(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        first = store.approval_wait(task_id)["since"]
        claim(store, clock, 73)
        assert store.task_status(task_id) == "draft"
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
        assert store.approval_wait(task_id)["since"] != first                 # not the old wait's start
        claim(store, clock, 1)
        assert store.task_status(task_id) == "queued"                         # and not ended at once
        assert len(events(store, "awaiting_approval")) == 2
        assert claim(store, clock, 72)["task"] is None and store.task_status(task_id) == "draft"


def test_a_skipped_occurrence_shows_no_false_dates_until_the_next_wait_begins(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store, recurring="true", recurring_min_interval="3600", scheduled_time="now")
        claim(store, clock)
        claim(store, clock, 73)
        shown = store.approval_wait(task_id)
        assert shown == dict(since=None, expires_at=None)
        claim(store, clock, 2)                                                # the next occurrence is found
        assert store.approval_wait(task_id)["since"] == events(store, "awaiting_approval")[-1]["ts"]


def test_the_console_read_never_writes_or_ends_a_wait_even_when_an_exclusive_task_waits(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        clock.advance(500)
        before = len(store.audit_lines())
        store.queue_waits(now=clock.local)
        assert len(store.audit_lines()) == before and store.task_status(task_id) == "queued"


def test_the_console_read_of_an_exclusive_waiter_writes_nothing(ready, clock):
    """A task that has waited long for a place is the drain target's candidate; judging it for a read
    must not record a wait, end one or write anything, which a read session could not do anyway."""
    with solar_state.session() as store:
        task_id = waiting(store)
        store.conn.execute("INSERT INTO claim_waits (task_id, first_blocked_at, reason) VALUES (?, ?, ?)",
                           (task_id, "2000-01-01T00:00:00Z", "global_capacity"))
        store.conn.commit()
        clock.advance(500)
        later = clock.local
    with solar_state.read_session() as reader:
        item = next(w for w in reader.queue_waits(now=later) if w["id"] == task_id)
        assert item["reason"] == "awaiting_approval"
    with solar_state.session() as store:
        assert events(store, "awaiting_approval") == [] and store.task_status(task_id) == "queued"


def test_starting_an_expired_task_by_name_ends_the_wait_and_says_so(ready, monkeypatch):
    monkeypatch.setenv(solar_state.APPROVAL_WAIT_ENV, "2")
    with solar_state.session() as store:
        task_id = waiting(store)
        soon = datetime.now()
        assert store.task_claim_detail(task_id, "worker", now=soon)["reason"] == "awaiting_approval"
        answer = store.task_claim_detail(task_id, "worker", now=soon + 3 * HOUR)
        assert answer["claimed"] is False and answer["reason"] == "approval_wait_expired"
        assert store.task_status(task_id) == "draft"
        assert events(store, "approval_wait_expired")[0]["outcome"] == "returned_to_draft"


def test_an_unreadable_start_is_no_start_and_never_the_year_1970(ready):
    with solar_state.session() as store:
        task_id = waiting(store)
        store.task_set(task_id, "approved_at", json.dumps("garbage"))
        assert store.approval_wait(task_id) == dict(since=None, expires_at=None)
        claim(store)
        assert store.task_status(task_id) == "queued"                          # not ended at once
        assert events(store, "awaiting_approval")[0]["since"] != "garbage"


def test_a_released_notice_is_offered_again_and_a_started_one_is_not(ready, clock):
    with solar_state.session() as store:
        waiting(store, title="A")
        waiting(store, title="B")
        claim(store, clock)
        first, second = [n["ref"] for n in store.approval_notices()]
        assert store.approval_notice_claim(first)
        store.approval_notice_result(first, True)                              # its send began: never again
        assert store.approval_notice_claim(second)
        store.approval_notice_release(second)                                  # nothing started: back
        assert [n["ref"] for n in store.approval_notices()] == [second]
        assert store.approval_notice_claim(second)                             # and it can be taken again


def test_the_notices_are_read_from_the_last_one_taken(ready, clock):
    with solar_state.session() as store:
        for n in range(3):
            waiting(store, title=f"Work {n}")
        claim(store, clock)
        first = store.approval_notices(1)
        assert len(first) == 1
        store.approval_notice_claim(first[0]["ref"])
        left = [n["ref"] for n in store.approval_notices()]
        assert len(left) == 2 and all(ref > first[0]["ref"] for ref in left)       # only what follows the one taken


def test_a_task_nobody_claimed_for_longer_than_the_limit_ends_at_its_first_claim(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        approved = fm(store, task_id)["approved_at"]
        clock.advance(100)
        shown = store.approval_wait(task_id)
        assert datetime.fromisoformat(shown["expires_at"].replace("Z", "+00:00")) < clock.at   # the view says it is over
        assert claim(store, clock)["task"] is None
        assert store.task_status(task_id) == "draft"                                           # and the claim agrees
        assert events(store, "awaiting_approval")[0]["since"] == approved


def test_the_view_and_the_limit_share_one_start(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        clock.advance(10)
        before = store.approval_wait(task_id)
        claim(store, clock)
        after = store.approval_wait(task_id)
        assert before == after                                                                  # recording changes nothing


def test_an_expiry_notice_is_not_sent_once_the_task_was_approved_and_authorized_again(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        claim(store, clock, 73)
        assert store.task_status(task_id) == "draft"
        ref = [n for n in store.approval_notices() if n["event"] == "approval_wait_expired"][0]["ref"]
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"], consent="client")
        store.task_authorize_run(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert store.approval_notice_claim(ref) is None                        # "back to draft" is no longer true


def test_an_expiry_notice_is_sent_while_it_is_still_true(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store)
        claim(store, clock)
        claim(store, clock, 73)
        ref = [n for n in store.approval_notices() if n["event"] == "approval_wait_expired"][0]["ref"]
        assert store.approval_notice_claim(ref)["outcome"] == "returned_to_draft"


def test_a_skipped_occurrence_notice_follows_the_approval_it_names(ready, clock):
    with solar_state.session() as store:
        task_id = waiting(store, recurring="true", recurring_min_interval="3600", scheduled_time="now")
        claim(store, clock)
        claim(store, clock, 73)
        ref = [n for n in store.approval_notices() if n["event"] == "approval_wait_expired"][0]["ref"]
        store.task_authorize_run(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert store.approval_notice_claim(ref) is None                        # authorized: nothing waits any more


def test_an_ended_wait_is_filed_under_authorization_in_the_console(ready):
    import runtime_views
    assert runtime_views.wait_kind("approval_wait_expired") == "authorization"
    assert runtime_views.wait_kind("awaiting_approval") == "authorization"


def test_notices_after_the_last_one_taken_are_offered_in_order_whatever_the_audit_holds(ready, clock):
    with solar_state.session() as store:
        for n in range(3):
            waiting(store, title=f"W{n}")
        claim(store, clock)
        for noise in range(50):                                                # unrelated audit rows in between
            store.conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?, ?, NULL, ?)",
                               ("2026-01-01T00:00:00Z", "other", json.dumps({"event": "other"})))
        store.conn.commit()
        refs = [n["ref"] for n in store.approval_notices()]
        assert len(refs) == 3 and refs == sorted(refs)
        store.approval_notice_claim(refs[0])
        store.approval_notice_claim(refs[1])
        store.approval_notice_release(refs[1])                                 # only the newest taken can come back
        assert [n["ref"] for n in store.approval_notices()] == refs[1:]


def _plan(store, sql, args):
    return " | ".join(r[3] for r in store.conn.execute("EXPLAIN QUERY PLAN " + sql, args))


def test_the_notice_queries_read_an_index_in_order_and_never_sort_the_history(ready):
    with solar_state.session() as store:
        newest = _plan(store, solar_state.Session._NOTICE_NEWEST_FIRST, ())
        pending = _plan(store, solar_state.Session._NOTICE_PENDING, ("awaiting_approval", "", 0))
        for plan in (newest, pending):
            assert "TEMP B-TREE" not in plan, plan                     # no sorting of the whole history
            assert "audit_event" in plan, plan                         # and both come from the index


def _steps(store, work):
    """The SQLite virtual-machine steps `work()` took, a measure of how much of the audit it read."""
    counted = []
    store.conn.set_progress_handler(lambda: counted.append(1) or 0, 100)
    try:
        work()
    finally:
        store.conn.set_progress_handler(None, 0)
    return len(counted)


def test_neither_notice_query_reads_the_history(ready):
    def fill(store, n):
        rows = []
        for i in range(n):
            ev = "awaiting_approval" if i % 2 == 0 else "approval_notice"
            body = {"event": ev, "task_id": f"t{i}", "digest": "d", "occurrence": "", "approval": "1"}
            if ev == "approval_notice":
                body["ref"] = i
            day = 1 + (start + i) // 1000                                 # time moves on as the audit grows
            rows.append(("2026-01-%02dT00:00:00Z" % day, ev, None, json.dumps(body)))
        store.conn.executemany("INSERT INTO audit (ts, event, router_id, row) VALUES (?,?,?,?)", rows)
        store.conn.commit()

    start = 0
    with solar_state.session() as store:
        fill(store, 200)
        small = _steps(store, lambda: store.approval_notices(1))
        start = 200
        fill(store, 20_000)
        large = _steps(store, lambda: store.approval_notices(1))
        # 100 times the history must not cost anything like 100 times the work: the margin of one day of
        # audit is all it may read (about 50 steps here), against thousands for the whole history
        assert large < 150, f"{small} steps on 200 rows, {large} on 20,200"


def test_a_wait_written_while_the_audit_clock_was_behind_is_still_offered(ready):
    with solar_state.session() as store:
        def put(event, ts, **body):
            store.conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?,?,NULL,?)",
                               (ts, event, json.dumps(dict(event=event, task_id="t", **body))))
            return store.conn.execute("SELECT MAX(seq) FROM audit").fetchone()[0]
        first = put("awaiting_approval", "2026-01-01T12:00:00Z", digest="d", occurrence="", approval="1")
        put("approval_notice", "2026-01-01T12:00:01Z", ref=first)
        later = put("awaiting_approval", "2026-01-01T11:00:00Z", digest="d", occurrence="", approval="1")
        store.conn.commit()                                                    # later in order, an hour behind in time
        assert [n["ref"] for n in store.approval_notices()] == [later]


def test_a_clock_that_went_back_never_changes_which_notice_comes_next(ready):
    """More waits than the batch, with times that go backwards: every one is offered once, in row order."""
    with solar_state.session() as store:
        stamps = ["10:00", "10:05", "09:00", "10:10", "08:30", "10:15", "09:45", "10:20"]
        refs = []
        for n, at in enumerate(stamps):
            store.conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?,?,NULL,?)",
                               (f"2026-01-01T{at}:00Z", "awaiting_approval",
                                json.dumps(dict(event="awaiting_approval", task_id=f"t{n}", digest="d",
                                                occurrence="", approval="1"))))
            refs.append(store.conn.execute("SELECT MAX(seq) FROM audit").fetchone()[0])
        store.conn.commit()
        offered = []
        while True:
            batch = store.approval_notices(3)
            if not batch:
                break
            for notice in batch:
                store.approval_notice_claim(notice["ref"])                     # taken (no such task: marked, not sent)
                offered.append(notice["ref"])
        assert offered == refs                                                 # all of them, once, in row order


def test_the_cursor_is_the_highest_row_taken_even_when_times_run_backwards(ready):
    with solar_state.session() as store:
        for ref, at in ((1, "10:00"), (2, "09:00"), (3, "08:00")):
            store.conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?,?,NULL,?)",
                               (f"2026-01-01T{at}:00Z", "approval_notice", json.dumps(dict(event="approval_notice", ref=ref))))
        store.conn.commit()
        assert store._notice_cursor()[0] == 3


def _audit_row(store, event, day, **body):
    store.conn.execute("INSERT INTO audit (ts, event, router_id, row) VALUES (?,?,NULL,?)",
                       (f"2026-01-{day:02d}T10:00:00Z", event, json.dumps(dict(event=event, **body))))
    return store.conn.execute("SELECT MAX(seq) FROM audit").fetchone()[0]


def test_a_returned_notice_does_not_reset_the_cursor_to_nothing(ready):
    """Three notices sent over three days, then days later a fourth is taken and given back."""
    with solar_state.session() as store:
        refs = [_audit_row(store, "awaiting_approval", day, task_id=f"t{day}", digest="d", occurrence="",
                           approval="1") for day in (1, 2, 3, 6)]
        for day, ref in zip((1, 2, 3), refs):
            _audit_row(store, "approval_notice", day, ref=ref)
        fourth = _audit_row(store, "approval_notice", 6, ref=refs[3])
        _audit_row(store, "approval_notice_released", 6, ref=refs[3])
        store.conn.commit()
        assert store._notice_cursor()[0] == refs[2]                            # the last one still taken, days older
        assert [n["ref"] for n in store.approval_notices()] == [refs[3]]       # only the one that was given back
        assert fourth > refs[3]


def test_the_cursor_skips_every_returned_notice_before_the_first_still_taken(ready):
    with solar_state.session() as store:
        refs = [_audit_row(store, "awaiting_approval", day, task_id=f"t{day}", digest="d", occurrence="",
                           approval="1") for day in (1, 20, 21)]
        _audit_row(store, "approval_notice", 1, ref=refs[0])
        for day, ref in ((20, refs[1]), (21, refs[2])):
            _audit_row(store, "approval_notice", day, ref=ref)
            _audit_row(store, "approval_notice_released", day, ref=ref)
        store.conn.commit()
        assert store._notice_cursor()[0] == refs[0]
        assert [n["ref"] for n in store.approval_notices()] == refs[1:]
