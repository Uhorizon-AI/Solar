"""Acceptance case, on synthetic data: prepare "Marketing: Weekly AI News" as a Friday editorial close.

Nothing here touches a real task, mandate, credential or workspace. The fixture
runtime is a temporary directory and the "current" task is built from scratch to
look like a daily digest. The preparation produces an unapproved draft.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import solar_state
import task_views
from mcp_helpers import execute, run, search, stored, queue_and_authorize
from reservation_tokens import token_of

MADRID = "Europe/Madrid"
TITLE = "Marketing: Weekly AI News"

CURRENT_BODY = """
# Marketing: Weekly AI News

Collect the AI news of the day and summarize it for the marketing channel.

## Result

Old output from a previous run.
"""

NEW_INSTRUCTIONS = """## Roles

- Marketing coordinates the weekly editorial close and owns the final report.
- Research verifies every news item against its source before it is included.
- Content Creator prepares the report from the verified items.

## Report

Write a short HTML report with the verified news of the week and exactly three
proposals for next week. Save it as a local file in the declared output folder.

## Limits

No automatic publication. Do not post, send or schedule anything outside the
machine. Publishing remains a separate decision made by a person.
"""


@pytest.fixture
def current(solar_env):
    """The synthetic "real" task: queued, recurring, daily, host-local, no time zone."""
    with solar_state.session() as store:
        task_id = store.task_create(
            [("title", json.dumps(TITLE)), ("planet", '"marketing"'), ("scope", '"marketing channel"'),
             ("object", '"Daily AI news digest"'), ("effect", '"local digest file"'),
             ("scheduled_time", '"09:00"'), ("recurring", "true"),
             ("recurring_min_interval", "86400"), ("recurring_run_count", "41")],
            CURRENT_BODY, status="queued")
        return task_id, store.task_export(task_id), store.task_get(task_id)["row_version"]


def test_the_task_can_be_found_and_read_by_name(solar_env, current):
    task_id, _, _ = current
    found = search(scope="tasks", query=TITLE)
    assert found["tasks"][0]["id"] == task_id and found["tasks"][0]["status"] == "queued"
    detail = search(scope="tasks", task_id=task_id)
    assert detail["planet"] == "marketing" and detail["schedule"]["time"] == "09:00"
    assert "No time zone stored" in detail["schedule"]["note"]
    assert "Collect the AI news" in search(scope="tasks", task_id=task_id, view="instructions")["instructions"]
    assert search(scope="tasks", task_id=task_id, view="result")["recorded"] is True
    assert search(scope="tasks", task_id=task_id, view="error")["recorded"] is False


def test_the_weekly_update_is_prepared_as_an_unapproved_revision(solar_env, current):
    task_id, exported, source_version = current

    revision = run("task.create", dict(
        title="Marketing: Weekly AI News (weekly editorial close)",
        instructions=NEW_INSTRUCTIONS, revises_task_id=task_id,
        object="Weekly editorial close of AI news",
        effect="Writes one local HTML report. No publication and no external send.",
        agent="marketing", responsibility="weekly-editorial-close"))
    scheduled = run("task.schedule", dict(
        task_id=revision["id"], expected_row_version=revision["row_version"],
        scheduled_time="17:00", scheduled_weekdays=[5], scheduled_timezone=MADRID, recurring=True))

    # Prepared, not activated; the current task is exactly as it was.
    draft = stored(revision["id"])
    assert draft["status"] == "draft" and scheduled["activated"] is False
    with solar_state.session() as store:
        assert store.task_export(task_id) == exported
        # Friday 17:01 local: the draft is not in the queue, so nothing is claimed.
        assert store.task_claim_next("worker", now=datetime(2027, 4, 2, 15, 1, tzinfo=timezone.utc)) is None
    assert stored(revision["id"])["status"] == "draft"

    # The report brief is explicit.
    body = draft["body"]
    for text in ("Marketing coordinates", "Research verifies", "Content Creator prepares",
                 "HTML report", "exactly three", "No automatic publication"):
        assert text in body
    values = {k: solar_state.value_of(v) for k, v in draft["frontmatter"]}
    assert values["planet"] == "marketing" and values["agent"] == "marketing"
    assert "No publication" in values["effect"] and "notify_when" not in values

    # Friday 17:00 Europe/Madrid, recurring weekly.
    assert values["scheduled_time"] == "17:00" and values["scheduled_weekdays"] == "5"
    assert values["scheduled_timezone"] == MADRID and values["recurring"] == "true"
    assert int(values["recurring_min_interval"]) < 7 * 86400
    assert "recurring_run_count" not in values   # a fresh recurrence, not the old counter

    # Approving it is blocked while the current task can still run.
    body, error = execute("task.approve", dict(task_id=revision["id"], expected_row_version=draft["row_version"]))
    assert error and body["code"] == "task_state_refused"


def test_correct_scheduling_across_clock_changes(solar_env):
    """Friday 17:00 local is 16:00Z in winter and 15:00Z in summer, in both directions."""
    spring = task_views.next_occurrences("17:00", [5], MADRID, datetime(2027, 3, 20, tzinfo=timezone.utc), 3)
    assert [(o["local"], o["utc"]) for o in spring] == [
        ("2027-03-26T17:00:00+01:00", "2027-03-26T16:00:00Z"),
        ("2027-04-02T17:00:00+02:00", "2027-04-02T15:00:00Z"),
        ("2027-04-09T17:00:00+02:00", "2027-04-09T15:00:00Z")]
    autumn = task_views.next_occurrences("17:00", [5], MADRID, datetime(2027, 10, 25, tzinfo=timezone.utc), 2)
    assert [o["utc"] for o in autumn] == ["2027-10-29T15:00:00Z", "2027-11-05T16:00:00Z"]


def test_the_queue_runs_it_at_17_local_on_both_sides_of_a_clock_change(solar_env):
    # Prepare and approve a synthetic standalone task (no original in the way).
    made = run("task.create", dict(title="Synthetic weekly close", instructions=NEW_INSTRUCTIONS,
                                   effect="Writes one local HTML report."))
    sched = run("task.schedule", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                      scheduled_time="17:00", scheduled_weekdays=[5],
                                      scheduled_timezone=MADRID, recurring=True))
    queue_and_authorize(made["id"], sched["row_version"])
    interval = sched["schedule"]["recurring_min_interval"]
    assert interval == 7 * 86400 - 7200

    def at(*parts):
        return datetime(*parts, tzinfo=timezone.utc)

    with solar_state.session() as store:
        assert store.task_claim_next("w", now=at(2027, 3, 26, 14, 0)) is None        # 15:00 local
        assert store.task_claim_next("w", now=at(2027, 3, 26, 16, 1))["id"] == made["id"]  # 17:01 CET
        store.task_set(made["id"], "recurring_last_run", json.dumps("2027-03-26T16:12:00Z"))
        store.task_complete(made["id"], token=token_of(store, made["id"]))
        assert store.task_get(made["id"])["status"] == "queued"
        # The next Friday the clock reads CEST: 15:01Z is 17:01 local. One week minus an hour has passed.
        assert store.task_claim_next("w", now=at(2027, 4, 2, 16, 1)) is None         # 18:01 local: too late
        assert store.task_claim_next("w", now=at(2027, 4, 2, 15, 1))["id"] == made["id"]


def test_the_report_cannot_publish_by_construction(solar_env, current):
    """No operation here sends or publishes: only telegram.send leaves the machine, and it is not called."""
    task_id, _, _ = current
    run("task.create", dict(title="x", instructions=NEW_INSTRUCTIONS, revises_task_id=task_id))
    rows = [json.loads(line) for line in solar_env.gate_audit.read_text().splitlines()]
    assert not any(r.get("tool") == "telegram.send" for r in rows)
    values = {k: solar_state.value_of(v) for k, v in
              stored(search(scope="tasks", query="x")["tasks"][0]["id"])["frontmatter"]}
    assert "executor" not in values and "local_command" not in values
