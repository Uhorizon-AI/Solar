"""The claim only takes a task whose approval covers what is stored.

Covers the definition/digest contract, the claim gate (`task_claim`,
`task_claim_next`), `task_return_to_draft`, the rename of a queued task and the
v5 migration that lets a base created before it accept `queued -> draft`.
"""
from __future__ import annotations

import json
import logging
import threading
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

import solar_state
from solar_state import TaskChanged, TransitionRefused

BODY = "\n# T\n\nBody.\n"


def fm(store, task_id):
    return {k: solar_state.value_of(v) for k, v in store.task_get(task_id)["frontmatter"]}


def queued(store, title="T", body=None, **extra):
    """A task as the MCP flow leaves it: created as a draft, then approved."""
    fields = [("title", json.dumps(title))] + [(k, v) for k, v in extra.items()]
    task_id = store.task_create(fields, body if body is not None else BODY.replace("# T", f"# {title}"))
    store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"])
    return task_id


def audit(store, event):
    return store.audit_rows(event)


# --------------------------------------------------------------------------
# the definition
# --------------------------------------------------------------------------

def test_definition_body_strips_runtime_sections():
    body = ("\n# T\n\nDo the work.\n\n## Subtask results\n\nchild said x\n\n"
            "## Delivery\n\nsent\n\n## Result\n\nok\n\n## Execution Error\n\nboom\n")
    assert solar_state.definition_body(body, "T") == "Do the work."
    # A block ends at the next `## ` heading: what follows an author's own section is kept.
    body = "\n# T\n\nStep.\n\n## Result\n\nreturn a summary\n\n## Notes\n\nkeep this\n"
    assert solar_state.definition_body(body, "T") == "Step.\n\n## Notes\n\nkeep this"


def test_definition_body_canonical_trailing_ws():
    base = solar_state.definition_body("\n# T\n\nDo it.\n", "T")
    for variant in ("\n# T\n\nDo it.", "\n# T\n\nDo it.\n\n\n", "# T\n\nDo it.  \n \n",
                    "\n# T\n\nDo it.\n\n## Delivery\n\nx"):
        assert solar_state.definition_body(variant, "T") == base == "Do it."


def test_the_title_heading_is_not_part_of_the_definition():
    assert solar_state.definition_text("\n# Old\n\nDo it.\n", "Old") == "Do it."
    assert solar_state.definition_text("\n# New\n\nDo it.\n", "New") == "Do it."
    # Only the heading that is the title: any other first line is the author's.
    assert solar_state.definition_text("\n# Other\n\nDo it.\n", "New") == "# Other\n\nDo it."
    pairs = [["title", ' "A"'], ["object", ' "o"']]
    renamed = [["title", ' "B"'], ["object", ' "o"']]
    assert solar_state.material_digest(pairs, "\n# A\n\nx\n") == \
        solar_state.material_digest(renamed, "\n# B\n\nx\n")
    assert solar_state.material_digest(pairs, "\n# A\n\nx\n").startswith("v2:")


def test_definition_snapshot_preferred_over_strip(ready):
    """An author's own `## Result` section is part of what was approved."""
    body = "\n# T\n\nStep one.\n\n## Result\n\nReturn exactly three bullets.\n"
    with solar_state.session() as store:
        task_id = queued(store, body=body)
        values = fm(store, task_id)
        assert "Return exactly three bullets." in values["approved_definition"]
        assert store.task_claim_next("w") is not None
        store.task_release(task_id, "w")
        # Changing the author's section changes the definition...
        store.task_set_body(task_id, body.replace("three", "thirty"))
        assert store.task_claim_next("w") is None
        # ...which the strip fallback alone would not have seen.
        stripped = solar_state.definition_body(body.replace("three", "thirty"), "T")
        assert stripped == solar_state.definition_body(body, "T") == "Step one."
        assert audit(store, "approval_digest_mismatch")[-1]["reason"] == "mismatch"


# --------------------------------------------------------------------------
# approve writes the digest, in both forms
# --------------------------------------------------------------------------

def test_approve_without_row_version_still_writes_digest(ready):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"'), ("object", '"o"')], BODY)
        store.task_approve(task_id)
        task = store.task_get(task_id)
        values = fm(store, task_id)
    assert task["status"] == "queued"
    assert values["approved_digest"] == solar_state.material_digest(task["frontmatter"], task["body"])
    assert values["approved_digest"].startswith("v2:")
    assert values["approved_definition"] == "Body."
    assert values["approved_row_version"] == "1" and values["approved_at"]


def test_cli_approve_leaves_a_digest_the_claim_accepts(ready):
    def cli(*args):
        return subprocess.run([sys.executable, solar_state.__file__, "--root", str(ready), *args],
                              capture_output=True, text=True)

    made = cli("task", "create", "--field", 'title="Desde Bash"', "--body", "\n# Desde Bash\n\nx\n")
    task_id = json.loads(made.stdout)["id"]
    assert cli("task", "approve", task_id).returncode == 0
    won = cli("task", "claim", task_id, "--worker", "w")
    assert won.returncode == 0 and json.loads(won.stdout)["claimed"] is True


def test_a_task_created_queued_carries_its_own_approval(ready):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"Q"')], "\n# Q\n\nx\n", status="queued")
        assert fm(store, task_id)["approved_digest"].startswith("v2:")
        assert store.task_claim(task_id, "w") is True


# --------------------------------------------------------------------------
# the claim gate
# --------------------------------------------------------------------------

def _legacy(store, task_id):
    store.task_set(task_id, "approved_digest", '"' + "a" * 64 + '"')


def _absent(store, task_id):
    for key in solar_state.APPROVAL_KEYS:
        store.task_unset(task_id, key)


def _mismatch(store, task_id):
    store.task_set_body(task_id, BODY + "\nAlso delete everything.\n")


@pytest.mark.parametrize("break_it,reason", [(_absent, "absent"), (_legacy, "legacy"),
                                             (_mismatch, "mismatch")])
@pytest.mark.parametrize("path", ["claim", "claim_next"])
def test_claim_and_claim_next_same_digest_gate(ready, break_it, reason, path):
    with solar_state.session() as store:
        task_id = queued(store)
        break_it(store, task_id)

        def attempt():
            if path == "claim":
                return store.task_claim_detail(task_id, "w")
            task = store.task_claim_next("w")
            return dict(claimed=task is not None)

        assert attempt()["claimed"] is False
        assert store.task_status(task_id) == "queued"
        if path == "claim":
            assert store.task_claim_detail(task_id, "w")["reason"] == reason
        assert audit(store, "approval_digest_mismatch")[-1]["reason"] == reason
        # Approved again over the stored content, the same task is taken.
        version = store.task_get(task_id)["row_version"]
        store.task_return_to_draft(task_id, expected_row_version=version)
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert attempt()["claimed"] is True


def test_claim_skips_digest_mismatch(ready):
    with solar_state.session() as store:
        first = queued(store, "First", priority='"high"')
        second = queued(store, "Second", priority='"normal"')
        store.task_set_body(first, BODY + "\nsneaked in\n")
        claimed = store.task_claim_next("w")
        assert claimed["id"] == second
        assert store.task_status(first) == "queued"
        assert store.task_claim_next("w2") is None


def test_approval_digest_mismatch_emits_audit(ready, caplog):
    with solar_state.session() as store:
        task_id = queued(store)
        _legacy(store, task_id)
        version = store.task_get(task_id)["row_version"]
        with caplog.at_level(logging.WARNING, logger="solar_state"):
            for _ in range(3):
                assert store.task_claim_next("w") is None
        rows = audit(store, "approval_digest_mismatch")
        # One row per task, reason and row version: a poll every minute is not a flood.
        assert len(rows) == 1
        assert rows[0]["task_id"] == task_id and rows[0]["reason"] == "legacy"
        assert rows[0]["row_version"] == version
        assert sum("approval_digest_mismatch" in m for m in caplog.messages) == 3


def test_legacy_digest_algorithm_fail_closed_or_migrates(ready):
    """Old algorithm: sha256 of title + raw body. It is refused, never converted."""
    import hashlib
    with solar_state.session() as store:
        task_id = queued(store)
        task = store.task_get(task_id)
        old = hashlib.sha256(json.dumps(dict(fields={}, body=task["body"]), sort_keys=True)
                             .encode()).hexdigest()
        store.task_set(task_id, "approved_digest", json.dumps(old))
        assert store.task_claim_detail(task_id, "w") == dict(claimed=False, reason="legacy")
        assert fm(store, task_id)["approved_digest"] == old        # no backfill
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        store.task_approve(task_id)
        assert store.task_claim(task_id, "w") is True


def test_a_recurring_task_keeps_passing_the_gate_after_it_ran(ready):
    """Delivery and results appended by the runtime are not a change of the definition."""
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="3600")
        assert store.task_claim_next("w")["id"] == task_id
        body = store.task_get(task_id)["body"]
        store.task_set_body(task_id, body.rstrip() + "\n\n## Result\n\ndone\n\n## Delivery\n\nsent\n")
        assert store.task_complete(task_id) == "queued"
        assert store.task_claim(task_id, "w") is True
        store.task_set_body(task_id, store.task_get(task_id)["body"].rstrip() + "\n\n## Execution Error\n\nx\n")
        store.task_fail(task_id, "")
        store.task_requeue(task_id)
        assert store.task_claim(task_id, "w") is True


def test_rejected_claim_does_not_stamp_last_run(ready):
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="3600")
        _mismatch(store, task_id)
        before = store.task_get(task_id)
        assert store.task_claim_next("w") is None
        assert store.task_claim(task_id, "w") is False
        after = store.task_get(task_id)
        assert after["frontmatter"] == before["frontmatter"]
        assert after["row_version"] == before["row_version"]
        assert "recurring_last_run" not in fm(store, task_id)


# --------------------------------------------------------------------------
# rename keeps the approval
# --------------------------------------------------------------------------

def test_edit_queued_preserves_run_count_and_last_run(ready):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="86400",
                         recurring_run_count="2", recurring_last_run=json.dumps(stamp))
        rows = len(store.task_list())
        events = len(audit(store, "task_renamed"))
        version = store.task_get(task_id)["row_version"]
        approved = fm(store, task_id)["approved_digest"]
        out = store.task_update(
            task_id, expected_row_version=version, allowed_status=("draft", "planned", "queued"),
            fields={"title": '"Renamed"'},
            body=BODY.replace("# T", "# Renamed"), actor="test")
        values = fm(store, task_id)
        assert out["status"] == "queued" and out["row_version"] == version + 1
        assert len(store.task_list()) == rows
        assert values["title"] == "Renamed" and values["approved_digest"] == approved
        assert values["recurring_run_count"] == "2" and values["recurring_last_run"] == stamp
        assert len(audit(store, "task_renamed")) == events + 1
        assert audit(store, "task_renamed")[-1]["to_title"] == "Renamed"
        # Still approved, still the same task: the interval alone keeps it waiting.
        assert store.task_claim_next("w") is None
        assert audit(store, "approval_digest_mismatch") == []
        assert store.task_claim(task_id, "w") is True


def test_a_queued_edit_that_changes_the_approved_content_is_refused_here(ready):
    with solar_state.session() as store:
        task_id = queued(store)
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TransitionRefused, match="return it to draft"):
            store.task_update(task_id, expected_row_version=version,
                              allowed_status=("queued",), fields={"object": '"x"'})
        with pytest.raises(solar_state.StateError):
            store.task_update(task_id, expected_row_version=version, allowed_status=("queued",),
                              fields={"approved_digest": '"v2:00"'})
        assert store.task_get(task_id)["row_version"] == version


# --------------------------------------------------------------------------
# return to draft
# --------------------------------------------------------------------------

def test_return_to_draft_keeps_the_task_and_withdraws_the_approval(ready):
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_run_count="3",
                         recurring_last_run='"2026-10-01T00:00:00Z"')
        rows = len(store.task_list())
        before = store.task_get(task_id)
        approved = fm(store, task_id)["approved_digest"]
        out = store.task_return_to_draft(task_id, expected_row_version=before["row_version"],
                                         actor="mcp:test")
        after = store.task_get(task_id)
        values = fm(store, task_id)
        assert out["status"] == "draft" and out["withdrawn"]["approved_digest"] == approved
        assert after["status"] == "draft" and after["body"] == before["body"]
        assert len(store.task_list()) == rows
        assert not set(solar_state.APPROVAL_KEYS) & set(values)
        assert values["recurring_run_count"] == "3"
        assert values["recurring_last_run"] == "2026-10-01T00:00:00Z"
        events = [(e["from_status"], e["to_status"]) for e in store.conn.execute(
            "SELECT from_status, to_status FROM task_events WHERE task_id = ? ORDER BY seq", (task_id,))]
        assert events[-1] == ("queued", "draft")
        withdrawn = audit(store, "task_approval_withdrawn")[-1]
        assert withdrawn["task_id"] == task_id and withdrawn["approved_digest"] == approved
        assert store.task_claim_next("w") is None            # nothing to claim
        assert store.task_claim(task_id, "w") is False


def test_return_to_draft_refuses_other_states_and_stale_versions(ready):
    with solar_state.session() as store:
        task_id = queued(store)
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_return_to_draft(task_id, expected_row_version=version + 1)
        assert store.task_status(task_id) == "queued"
        store.task_claim(task_id, "w")
        with pytest.raises(TransitionRefused, match="not queued"):
            store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert store.task_status(task_id) == "active"
        with pytest.raises(TransitionRefused):
            store.task_return_to_draft("nope", expected_row_version=1)


def test_claim_vs_return_to_draft_one_winner(ready):
    for _ in range(12):
        with solar_state.session() as store:
            task_id = queued(store)
            version = store.task_get(task_id)["row_version"]
        outcome = {}
        barrier = threading.Barrier(2)

        def claim():
            with solar_state.session() as store:
                barrier.wait()
                outcome["claim"] = store.task_claim(task_id, "w")

        def draft():
            with solar_state.session() as store:
                barrier.wait()
                try:
                    store.task_return_to_draft(task_id, expected_row_version=version)
                    outcome["draft"] = True
                except (TransitionRefused, TaskChanged) as exc:
                    outcome["draft"] = exc

        threads = [threading.Thread(target=claim), threading.Thread(target=draft)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        drafted = outcome["draft"] is True
        assert outcome["claim"] != drafted                  # exactly one wins
        with solar_state.session() as store:
            assert store.task_status(task_id) == ("draft" if drafted else "active")
            if not drafted:
                assert isinstance(outcome["draft"], (TransitionRefused, TaskChanged))
                assert "approved_digest" in fm(store, task_id)


def test_reapprove_does_not_reset_counters(ready):
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_run_count="4", recurring_max_runs="9",
                         recurring_last_run='"2026-10-01T00:00:00Z"')
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        values = fm(store, task_id)
        assert values["recurring_run_count"] == "4" and values["recurring_max_runs"] == "9"
        assert values["recurring_last_run"] == "2026-10-01T00:00:00Z"
        assert values["approved_digest"].startswith("v2:") and store.task_status(task_id) == "queued"


def test_no_extra_run_within_min_interval_after_edit_reapprove(ready):
    now = datetime.now(timezone.utc)
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="86400",
                         recurring_last_run=json.dumps((now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")))
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        store.task_approve(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert store.task_claim_next("w") is None            # one hour into a one day interval
        assert store.task_status(task_id) == "queued"
        later = datetime.now() + timedelta(days=2)
        assert store.task_claim_next("w", now=later)["id"] == task_id


# --------------------------------------------------------------------------
# the migration
# --------------------------------------------------------------------------

def test_migration_inserts_queued_to_draft_on_existing_db(ready):
    """A base migrated before v5 has no queued->draft row; the migration adds it."""
    with solar_state.session() as store:
        task_id = queued(store)
        rows_before = [tuple(r) for r in store.conn.execute("SELECT id, row_version, frontmatter FROM tasks")]
        store.conn.execute("DELETE FROM transitions WHERE from_status='queued' AND to_status='draft'")
        store.conn.execute("PRAGMA user_version = 4")
    with pytest.raises(solar_state.StateUnavailable, match="migration has not run"):
        with solar_state.session():
            pass
    with solar_state.cutover(ready) as cut:
        result = cut.upgrade_schema()
        again = cut.upgrade_schema()
    assert result["from_version"] == 4 and result["to_version"] == solar_state.SCHEMA_VERSION == 5
    assert result["backup"], "an existing base is copied first"
    assert again["from_version"] == 5 and again["backup"] is None     # idempotent
    with solar_state.session() as store:
        assert store.conn.execute(
            "SELECT COUNT(*) FROM transitions WHERE from_status='queued' AND to_status='draft'"
        ).fetchone()[0] == 1
        assert [tuple(r) for r in store.conn.execute(
            "SELECT id, row_version, frontmatter FROM tasks")] == rows_before
        store.task_return_to_draft(task_id, expected_row_version=store.task_get(task_id)["row_version"])
        assert store.task_status(task_id) == "draft"


def test_transitions_constant_matches_the_seeded_table(ready):
    with solar_state.session() as store:
        table = {tuple(r) for r in store.conn.execute("SELECT from_status, to_status FROM transitions")}
    assert table == set(solar_state.TRANSITIONS) and ("queued", "draft") in table
