"""A task that waits for `task.authorize_run` is visible where people look: the task list, the task
itself and the console, with when the wait began and when it ends. Nothing here reaches a service."""
from __future__ import annotations

import runtime_views
import solar_state
from mcp_helpers import call, execute, search

CLIENT_CONSENT = True


def ask(operation, arguments):
    return call("solar_execute", dict(operation=operation, arguments=arguments))


def make(title, **extra):
    body, error = ask("task.create", dict(title=title, instructions="Do it.", **extra))
    assert not error, body
    return body["result"]


def claim(task_id):
    with solar_state.session() as store:
        return store.task_claim_detail(task_id, "worker")


def listed(task_id):
    return next(t for t in search(scope="tasks", limit=50)["tasks"] if t["id"] == task_id)


def test_the_task_list_says_which_tasks_wait_and_since_when(solar_env):
    waiting = make("Waits", queue=True)
    draft = make("Just a draft")
    claim(waiting["id"])
    row = listed(waiting["id"])
    assert row["awaiting_approval"] is True and row["waiting_since"] and row["waiting_expires_at"]
    assert "awaiting_approval" not in listed(draft["id"]) and "waiting_since" not in listed(draft["id"])


def test_the_task_itself_carries_the_same_dates(solar_env):
    made = make("Waits", queue=True)
    claim(made["id"])
    for view in ("detail", "status"):
        shown = search(scope="tasks", task_id=made["id"], view=view)
        assert shown["awaiting_approval"] is True
        assert shown["waiting_since"] == listed(made["id"])["waiting_since"]
        assert shown["waiting_expires_at"] == listed(made["id"])["waiting_expires_at"]


def test_authorizing_clears_the_wait_from_every_view(solar_env):
    made = make("Waits", queue=True)
    claim(made["id"])
    execute("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert "awaiting_approval" not in listed(made["id"])
    shown = search(scope="tasks", task_id=made["id"], view="detail")
    assert shown["awaiting_approval"] is False and shown["waiting_since"] is None


def test_the_console_shows_the_wait_with_its_dates(solar_env):
    made = make("Waits", queue=True)
    claim(made["id"])
    with solar_state.read_session() as store:
        data = runtime_views.console_capacity(store)
    item = next(w for w in data["waiting"] if w["id"] == made["id"])
    assert item["reason"] == "awaiting_approval" and item["kind"] == "authorization"
    assert item["since"] and item["expires_at"]
    assert data["wait_counts"]["authorization"] >= 1
