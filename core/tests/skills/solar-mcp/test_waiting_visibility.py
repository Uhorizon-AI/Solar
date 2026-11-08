"""A task that waits for `task.authorize_run` is visible where people look: the task list, the task
itself and the console, with when the wait began and when it ends. Nothing here reaches a service."""
from __future__ import annotations

import json

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


def _task_with_id(task_id, title="T"):
    with solar_state.session() as store:
        return store.task_create([("title", f'"{title}"')], f"\n{title}\n", task_id=task_id)


def test_the_short_id_in_the_notice_names_one_task_and_leads_to_authorization(solar_env):
    made = make("Waits", queue=True)
    claim(made["id"])
    short = made["id"][:8]
    shown = search(scope="tasks", task_id=short, view="detail")          # the prefix, as the notice shows it
    assert shown["id"] == made["id"] and shown["awaiting_approval"] is True
    out, error = execute("task.authorize_run", dict(task_id=shown["id"], expected_row_version=shown["row_version"]))
    assert not error, out
    assert "awaiting_approval" not in listed(made["id"])


def test_a_title_that_contains_the_prefix_does_not_confuse_it(solar_env):
    other = make("abcdef12 in the title")
    target = _task_with_id("abcdef12-aaaa-4000-8000-000000000001", "Target")
    assert search(scope="tasks", task_id="abcdef12", view="status")["id"] == target
    assert other["id"] != target


def test_an_ambiguous_prefix_is_refused_and_an_exact_id_wins(solar_env):
    shorter = _task_with_id("abcdef12", "Exact")
    longer = _task_with_id("abcdef12-0001", "Longer")
    body, error = call("solar_search", dict(scope="tasks", task_id="abcdef1", view="status"))
    assert error                                                     # 7 characters: not a short id
    body, error = call("solar_search", dict(scope="tasks", task_id="abcdef12-00", view="status"))
    assert not error and body["result"]["id"] == longer              # one match
    assert search(scope="tasks", task_id="abcdef12", view="status")["id"] == shorter    # exact beats prefix
    _task_with_id("abcdef12-0002", "Second")
    body, error = call("solar_search", dict(scope="tasks", task_id="abcdef12-", view="status"))
    assert error and "task_ambiguous" in json.dumps(body)


def test_a_file_name_and_a_prefix_that_name_different_tasks_are_ambiguous(solar_env):
    target = _task_with_id("abcdef12-aaaa-4000-8000-000000000001", "Target")
    imported = _task_with_id("zzz-imported-task", "Imported")
    with solar_state.session() as store:
        store.conn.execute("UPDATE tasks SET source_name = ? WHERE id = ?", ("abcdef12.md", imported))
    body, error = call("solar_search", dict(scope="tasks", task_id="abcdef12", view="status"))
    assert error and "task_ambiguous" in json.dumps(body)
    assert search(scope="tasks", task_id=target, view="status")["id"] == target     # the full id still works
    assert search(scope="tasks", task_id="abcdef12-aaaa", view="status")["id"] == target
    assert search(scope="tasks", task_id="zzz-imported-task", view="status")["id"] == imported


def test_a_file_name_alone_still_finds_its_task(solar_env):
    imported = _task_with_id("plain-task", "Imported")
    with solar_state.session() as store:
        store.conn.execute("UPDATE tasks SET source_name = ? WHERE id = ?", ("old-name.md", imported))
    assert search(scope="tasks", task_id="old-name", view="status")["id"] == imported
