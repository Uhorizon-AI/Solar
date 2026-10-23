"""A question (`ask_readonly_v1`) is a reader like any other: it runs next to other tasks only when the
applied policy lists the profile, and then the global and per-provider limits apply. These tests use the
real profile registry on purpose (no simulated adapter): the registry already verifies the profile for
all four clients, so enabling it is the whole switch, and capacity 1 or an empty list is the way back."""
from __future__ import annotations

import json

import pytest

import solar_state
from reservation_tokens import token_of

ASK = "ask_readonly_v1"
PROVIDERS = ("codex", "claude", "agent", "agy")


def access(scopes=("/ws",)):
    return json.dumps(dict(version=1, mode="read", scopes=list(scopes), resources=[]),
                      sort_keys=True, separators=(",", ":"))


def question(store, title, provider, scopes=("/ws",), profile=ASK):
    fields = [("title", json.dumps(title)), ("provider", json.dumps(provider)),
              ("access_policy", access(scopes))]
    if profile:
        fields.append(("execution_profile", json.dumps(profile)))
    task_id = store.task_create(fields, f"\n# {title}\n\nAsk {title}.\n", task_id=title.lower().replace(" ", "-"))
    store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"])
    return task_id


def set_policy(store, **changes):
    current = store.async_policy()
    document = dict(schema_version=1, revision=current["revision"] + 1,
                    global_capacity=current["global_capacity"],
                    provider_capacity=current["provider_capacity"],
                    exclusive_wait_seconds=current["exclusive_wait_seconds"],
                    enabled_reader_profiles=current["enabled_reader_profiles"])
    document.update(changes)
    return store.async_policy_apply(document, actor="test")


def claim(store, task_id):
    return store.task_claim_detail(task_id, "w")


@pytest.fixture
def store(ready):
    with solar_state.session(ready, auto_backup=False) as s:
        yield s


def test_the_registry_verifies_the_question_profile_for_the_four_clients():
    assert solar_state.VERIFIED_PROFILES[ASK] == frozenset(PROVIDERS)


def test_questions_run_alone_until_the_profile_is_enabled(store):
    set_policy(store, global_capacity=5, enabled_reader_profiles=[])
    first, second = question(store, "First", "codex"), question(store, "Second", "claude")
    assert claim(store, first)["claimed"]
    assert claim(store, second)["reason"] == "exclusive_needs_idle"
    assert store.reservation_for(first)["access_class"] == "exclusive"


def test_three_different_clients_run_at_the_same_time_once_enabled(store):
    set_policy(store, global_capacity=3, provider_capacity={"agent": 1}, enabled_reader_profiles=[ASK])
    ids = [question(store, f"Q {p}", p) for p in ("codex", "claude", "agent")]
    assert all(claim(store, t)["claimed"] for t in ids)
    assert {r["access_class"] for r in store.reservations()} == {"declared"}


def test_three_questions_to_the_same_client_run_together_within_its_limit(store):
    set_policy(store, global_capacity=5, provider_capacity={"codex": 3}, enabled_reader_profiles=[ASK])
    ids = [question(store, f"Codex {i}", "codex") for i in range(4)]
    assert all(claim(store, t)["claimed"] for t in ids[:3])
    assert claim(store, ids[3]) == dict(claimed=False, reason="provider_capacity")


def test_a_client_with_a_limit_of_one_runs_one_question_at_a_time(store):
    set_policy(store, global_capacity=5, provider_capacity={"agent": 1}, enabled_reader_profiles=[ASK])
    one, two = question(store, "Cursor one", "agent"), question(store, "Cursor two", "agent")
    assert claim(store, one)["claimed"]
    assert claim(store, two)["reason"] == "provider_capacity"
    store.task_complete(one, token=token_of(store, one))
    assert claim(store, two)["claimed"]


def test_going_back_to_capacity_one_serializes_questions_again(store):
    set_policy(store, global_capacity=3, enabled_reader_profiles=[ASK])
    set_policy(store, global_capacity=1)
    first, second = question(store, "First", "codex"), question(store, "Second", "claude")
    assert claim(store, first)["claimed"]
    assert claim(store, second)["reason"] == "global_capacity"


def test_removing_the_profile_from_the_policy_is_the_other_way_back(store):
    set_policy(store, global_capacity=3, enabled_reader_profiles=[ASK])
    set_policy(store, enabled_reader_profiles=[])
    first, second = question(store, "First", "codex"), question(store, "Second", "claude")
    assert claim(store, first)["claimed"]
    assert claim(store, second)["reason"] == "exclusive_needs_idle"


def test_a_task_that_declares_nothing_still_runs_alone_next_to_questions(store):
    set_policy(store, global_capacity=3, enabled_reader_profiles=[ASK])
    asked = question(store, "Asked", "codex")
    plain = store.task_create([("title", json.dumps("Plain")), ("provider", json.dumps("codex"))],
                              "\n# Plain\n\nDo it.\n", task_id="plain")
    store.task_approve(plain, expected_row_version=store.task_get(plain)["row_version"])
    assert claim(store, asked)["claimed"]
    assert claim(store, plain)["reason"] == "exclusive_needs_idle"


def test_enabling_the_question_profile_does_not_make_an_unprofiled_declaration_concurrent(store):
    set_policy(store, global_capacity=5, enabled_reader_profiles=[ASK])
    one = question(store, "One", "codex", scopes=("/a",), profile=None)
    two = question(store, "Two", "codex", scopes=("/b",), profile=None)
    assert claim(store, one)["claimed"]
    assert claim(store, two)["reason"] == "exclusive_needs_idle"
