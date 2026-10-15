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


def test_material_edit_invalidates_approval_keeps_counters(ready):
    stamp = "2026-10-01T00:00:00Z"
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="86400",
                         recurring_run_count="2", recurring_last_run=json.dumps(stamp),
                         recurring_max_runs="9")
        approved = fm(store, task_id)["approved_digest"]
        rows = len(store.task_list())
        allowed = ("draft", "planned", "queued")
        for change in (dict(fields={"object": '"x"'}), dict(fields={"scheduled_time": '"17:00"'}),
                       dict(fields={"resources": '"db"'}),
                       dict(definition="\n# T\n\nOther steps.\n")):
            version = store.task_get(task_id)["row_version"]
            out = store.task_update(task_id, expected_row_version=version, allowed_status=allowed,
                                    actor="test", **change)
            values = fm(store, task_id)
            assert out["status"] == "draft" and out["returned_to_draft"] is True
            assert not set(solar_state.APPROVAL_KEYS) & set(values), change
            assert values["recurring_run_count"] == "2" and values["recurring_last_run"] == stamp
            assert values["recurring_max_runs"] == "9" and len(store.task_list()) == rows
            assert store.task_claim_next("w") is None and store.task_claim(task_id, "w") is False
            withdrawn = audit(store, "task_approval_withdrawn")[-1]
            assert withdrawn["approved_digest"] == approved and withdrawn["reason"] == "material_edit"
            assert [e[0] for e in store.conn.execute(
                "SELECT to_status FROM task_events WHERE task_id = ? ORDER BY seq DESC LIMIT 2",
                (task_id,))] == ["draft", "queued"]
            # Approved again, it queues with a digest of the new content only.
            store.task_approve(task_id, expected_row_version=out["row_version"])
            assert fm(store, task_id)["approved_digest"] != approved
            approved = fm(store, task_id)["approved_digest"]


def test_a_stale_version_or_a_claim_beats_a_material_edit(ready):
    with solar_state.session() as store:
        task_id = queued(store)
        version = store.task_get(task_id)["row_version"]
        with pytest.raises(TaskChanged):
            store.task_update(task_id, expected_row_version=version + 1, allowed_status=("queued",),
                              fields={"object": '"x"'})
        assert store.task_claim(task_id, "w") is True
        with pytest.raises(TransitionRefused):
            store.task_update(task_id, expected_row_version=version + 1, allowed_status=("queued",),
                              fields={"object": '"x"'})
        with pytest.raises(TransitionRefused, match="not queued"):
            store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                              allowed_status=("queued",), fields={"object": '"x"'})
        assert store.task_status(task_id) == "active"
        assert "object" not in fm(store, task_id)
        with pytest.raises(solar_state.StateError):
            store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                              allowed_status=("active",), fields={"approved_digest": '"v2:0"'})


def test_editing_the_instructions_keeps_what_earlier_runs_wrote(ready):
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="3600")
        store.task_claim_next("w")
        store.task_set_body(task_id, store.task_get(task_id)["body"].rstrip()
                            + "\n\n## Result\n\nfirst run output\n\n## Delivery\n\nsent\n")
        assert store.task_complete(task_id) == "queued"
        out = store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                                allowed_status=("queued",), definition="\n# T\n\nNew steps.\n")
        body = store.task_get(task_id)["body"]
        assert out["status"] == "draft"
        assert "New steps." in body and "Body." not in body
        assert "first run output" in body and "## Delivery" in body
        assert solar_state.definition_body(body, "T") == "New steps."
        store.task_approve(task_id)
        assert fm(store, task_id)["approved_definition"] == "New steps."
        assert store.task_claim_detail(task_id, "w")["claimed"] is True


def test_a_never_run_draft_has_its_sections_replaced_by_the_new_instructions(ready):
    with solar_state.session() as store:
        task_id = store.task_create([("title", '"T"')], "\n# T\n\nA.\n\n## Result\n\nreturn bullets\n")
        store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                          allowed_status=("draft",), definition="\n# T\n\nB.\n")
        assert store.task_get(task_id)["body"] == "\n# T\n\nB.\n"


def test_renaming_a_queued_error_is_not_possible_and_a_rename_never_requeues(ready):
    with solar_state.session() as store:
        task_id = queued(store)
        store.task_claim_next("w")
        store.task_fail(task_id, "\n## Execution Error\n\nboom\n")
        with pytest.raises(TransitionRefused):
            store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                              allowed_status=("draft", "planned", "queued"), fields={"title": '"New"'})
        assert store.task_status(task_id) == "error"


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


def test_claim_vs_material_edit_one_winner(ready):
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

        def edit():
            with solar_state.session() as store:
                barrier.wait()
                try:
                    outcome["edit"] = store.task_update(
                        task_id, expected_row_version=version, fields={"object": '"x"'},
                        allowed_status=("draft", "planned", "queued"))["status"]
                except (TransitionRefused, TaskChanged) as exc:
                    outcome["edit"] = exc

        threads = [threading.Thread(target=claim), threading.Thread(target=edit)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        edited = outcome["edit"] == "draft"
        assert outcome["claim"] != edited
        with solar_state.session() as store:
            # Whoever won, a claim never got content its approval does not cover.
            assert store.task_status(task_id) == ("draft" if edited else "active")
            assert ("object" in fm(store, task_id)) is edited


# --------------------------------------------------------------------------
# review round: generated content with headings of its own, executor keys,
# imports, stamping in the claim, the list of what the worker refuses
# --------------------------------------------------------------------------

def test_results_with_their_own_headings_do_not_block_the_next_run(ready):
    with solar_state.session() as store:
        task_id = queued(store, recurring="true", recurring_min_interval="3600")
        assert store.task_claim_next("w")["id"] == task_id
        body = store.task_get(task_id)["body"].rstrip()
        store.task_set_body(task_id, body + "\n\n## Subtask results\n\n## Findings\n\nx\n\n"
                            "## Result\n\nok\n\n## Resumen\n\nmore\n\n## Delivery\n\nsent\n")
        assert store.task_complete(task_id) == "queued"
        assert store.task_claim_detail(task_id, "w") == dict(claimed=True, reason=None)
        # Something that is not generated, put after the instructions, still mismatches.
        store.task_complete(task_id)
        store.task_set_body(task_id, store.task_get(task_id)["body"].replace(
            "## Subtask results", "Also wipe the disk.\n\n## Subtask results", 1))
        assert store.task_claim_detail(task_id, "w") == dict(claimed=False, reason="mismatch")


def test_a_section_added_to_the_instructions_is_material_even_if_named_like_a_result(ready):
    with solar_state.session() as store:
        task_id = queued(store)
        out = store.task_update(
            task_id, expected_row_version=store.task_get(task_id)["row_version"],
            allowed_status=("draft", "planned", "queued"),
            definition="\n# T\n\nBody.\n\n## Result\n\nAlso delete the backup.\n")
        assert out["status"] == "draft" and out["returned_to_draft"] is True
        assert store.task_claim_next("w") is None
        store.task_approve(task_id)
        assert fm(store, task_id)["approved_definition"].endswith("Also delete the backup.")
        assert store.task_claim_detail(task_id, "w")["claimed"] is True


@pytest.mark.parametrize("key,value", [("executor", "local"), ("local_command", '"bash evil.sh"'),
                                       ("local_timeout", "999")])
@pytest.mark.parametrize("path", ["claim", "claim_next"])
def test_the_executor_is_part_of_what_is_approved(ready, key, value, path):
    with solar_state.session() as store:
        task_id = queued(store)
        store.task_set(task_id, key, value)
        if path == "claim":
            assert store.task_claim_detail(task_id, "w") == dict(claimed=False, reason="mismatch")
        else:
            assert store.task_claim_next("w") is None
        assert store.task_status(task_id) == "queued"


def test_an_imported_queued_task_keeps_its_results_when_its_instructions_are_edited(ready):
    document = ('---\nid: "imp"\ntitle: "Imported"\nstatus: queued\n---\n\n# Imported\n\nSteps.\n\n'
                '## Result\n\nlast week output\n\n## Delivery\n\nsent\n')
    with solar_state.session() as store:
        store.task_import(document)
        assert store.task_claim_next("w") is None                 # no approval: fail-closed
        out = store.task_update("imp", expected_row_version=store.task_get("imp")["row_version"],
                                allowed_status=("draft", "planned", "queued"),
                                definition="\n# Imported\n\nNew steps.\n")
        body = store.task_get("imp")["body"]
        assert out["status"] == "draft"
        assert "New steps." in body and "Steps." not in body.replace("New steps.", "")
        assert "last week output" in body and "## Delivery" in body
        # With recorded results the new instructions cannot reuse their section names.
        store.task_import(document.replace('"imp"', '"imp2"'))
        with pytest.raises(solar_state.StateError, match="cannot contain a section named"):
            store.task_update("imp2", expected_row_version=store.task_get("imp2")["row_version"],
                              allowed_status=("queued",), definition="\n# Imported\n\nX\n\n## Result\n\ny\n")
        assert store.task_status("imp2") == "queued"


def test_the_claim_stamps_the_interval_in_its_own_transaction(ready):
    with solar_state.session() as store:
        recurring = queued(store, "R", recurring="true", recurring_min_interval="3600")
        plain = queued(store, "P")
        stuck = queued(store, "S", recurring="true")
        _mismatch(store, stuck)
        assert store.task_claim_detail(recurring, "w", stamp_last_run=True)["claimed"] is True
        assert fm(store, recurring)["recurring_last_run"].endswith("Z")
        assert store.task_claim_detail(plain, "w", stamp_last_run=True)["claimed"] is True
        assert "recurring_last_run" not in fm(store, plain)
        assert store.task_claim_detail(stuck, "w", stamp_last_run=True)["claimed"] is False
        assert "recurring_last_run" not in fm(store, stuck)


def test_list_unapproved_names_what_the_worker_will_not_take(ready):
    with solar_state.session() as store:
        good = queued(store, "Good")
        legacy = queued(store, "Old")
        _legacy(store, legacy)
        gone = queued(store, "Gone")
        _absent(store, gone)
        changed = queued(store, "Changed")
        _mismatch(store, changed)
        found = {row["id"]: row["reason"] for row in store.tasks_unapproved()}
    assert found == {legacy: "legacy", gone: "absent", changed: "mismatch"} and good not in found

    def cli(*args):
        return subprocess.run([sys.executable, solar_state.__file__, "--root", str(ready), *args],
                              capture_output=True, text=True)

    shown = cli("task", "list-unapproved")
    assert shown.returncode == 0 and {r["id"] for r in json.loads(shown.stdout)} == set(found)


def test_renaming_a_task_whose_approval_is_not_valid_returns_it_to_draft(ready):
    with solar_state.session() as store:
        task_id = queued(store)
        _legacy(store, task_id)
        out = store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                                allowed_status=("queued",), fields={"title": '"Renamed"'},
                                body=BODY.replace("# T", "# Renamed"))
        assert out["status"] == "draft" and out["returned_to_draft"] is True
        assert not set(solar_state.APPROVAL_KEYS) & set(fm(store, task_id))


def test_results_stay_apart_from_the_instructions_through_successive_edits(ready):
    results = ("## Subtask results\n\n## Findings\n\nfirst\n\n### Detail\n\nx\n\n"
               "## Result\n\nok\n\n## Resumen\n\nmore\n\n## Delivery\n\nsent\n")
    for approve_between in (False, True):
        with solar_state.session() as store:
            task_id = queued(store, f"R{int(approve_between)}", recurring="true",
                             recurring_min_interval="3600")
            assert store.task_claim(task_id, "w") is True
            store.task_set_body(task_id, store.task_get(task_id)["body"].rstrip() + "\n\n" + results)
            assert store.task_complete(task_id) == "queued"
            title = store.task_get(task_id)["title"]
            for number in (1, 2, 3):
                store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                                  allowed_status=("draft", "planned", "queued"),
                                  definition=f"\n# {title}\n\nSteps v{number}.\n")
                body = store.task_get(task_id)["body"]
                assert results.strip() in body, (approve_between, number)
                assert f"Steps v{number}." in body and f"Steps v{number - 1}." not in body
                if approve_between or number == 3:
                    store.task_approve(task_id)
                    assert fm(store, task_id)["approved_definition"] == f"Steps v{number}."
                    assert store.task_claim_detail(task_id, "w")["claimed"] is True
                    store.task_complete(task_id)
                    assert results.strip() in store.task_get(task_id)["body"]


def test_an_imported_task_keeps_its_results_through_two_edits_as_a_draft(ready):
    document = ('---\nid: "imp3"\ntitle: "Imp"\nstatus: queued\n---\n\n# Imp\n\nSteps.\n\n'
                '## Result\n\nout\n\n## Findings\n\nf\n')
    with solar_state.session() as store:
        store.task_import(document)
        for number in (1, 2):
            store.task_update("imp3", expected_row_version=store.task_get("imp3")["row_version"],
                              allowed_status=("draft", "planned", "queued"),
                              definition=f"\n# Imp\n\nNew {number}.\n")
            assert "## Findings\n\nf" in store.task_get("imp3")["body"]
        store.task_approve("imp3")
        assert fm(store, "imp3")["approved_definition"] == "New 2."
        assert store.task_claim_detail("imp3", "w")["claimed"] is True


def test_the_console_survives_an_unreadable_frontmatter(ready):
    import runtime_views
    with solar_state.session() as store:
        good = queued(store, "Good")
        broken = queued(store, "Broken")
        store.conn.execute("UPDATE tasks SET frontmatter = 'not json' WHERE id = ?", (broken,))
        assert {r["id"]: r["reason"] for r in store.tasks_unapproved()} == {broken: "absent"}
    with solar_state.read_session() as store:
        tasks = {t["id"]: t for t in runtime_views.console_tasks(store)["tasks"]}
    assert tasks[good]["revises_task_id"] is None and tasks[broken]["revises_task_id"] is None
    assert tasks[broken]["approval_digest_mismatch"]["reason"] == "absent"


_IMPORTED = ('---\nid: "{id}"\ntitle: "Imp"\nstatus: {status}\n---\n\n# Imp\n\nSteps.\n\n'
             '## Result\n\nout\n\n## Findings\n\nf\n\n### Detail\n\nd\n\n## Delivery\n\nsent\n')
_RESULTS = "## Result\n\nout\n\n## Findings\n\nf\n\n### Detail\n\nd\n\n## Delivery\n\nsent"


def test_an_imported_task_returned_to_draft_keeps_its_results_through_edits(ready):
    with solar_state.session() as store:
        store.task_import(_IMPORTED.format(id="ret", status="queued"))
        store.task_return_to_draft("ret", expected_row_version=store.task_get("ret")["row_version"])
        assert fm(store, "ret")["definition_snapshot"] == "Steps."
        for number in (1, 2):
            store.task_update("ret", expected_row_version=store.task_get("ret")["row_version"],
                              allowed_status=("draft",), definition=f"\n# Imp\n\nNew {number}.\n")
            assert _RESULTS in store.task_get("ret")["body"]
        store.task_approve("ret")
        assert fm(store, "ret")["approved_definition"] == "New 2."
        assert store.task_claim_detail("ret", "w")["claimed"] is True


def test_an_imported_task_approved_before_the_edit_keeps_its_results(ready):
    with solar_state.session() as store:
        # As a draft, then approved, then edited: approving must not fold the results in.
        store.task_import(_IMPORTED.format(id="app", status="draft"))
        store.task_set("app", "recurring", "true")
        store.task_approve("app")
        assert fm(store, "app")["approved_definition"] == "Steps."
        assert store.task_claim_detail("app", "w")["claimed"] is True
        store.task_complete("app")
        for number in (1, 2):
            store.task_update("app", expected_row_version=store.task_get("app")["row_version"],
                              allowed_status=("draft", "planned", "queued"),
                              definition=f"\n# Imp\n\nNew {number}.\n")
            assert _RESULTS in store.task_get("app")["body"]
            store.task_approve("app")
            assert store.task_claim_detail("app", "w")["claimed"] is True
            store.task_complete("app")


def test_the_boundary_survives_losing_only_the_approval_fields(ready):
    """A manual clean-up that drops the digest and the approved snapshot, but not the boundary."""
    results = "## Result\n\nok\n\n## Findings\n\nf\n"
    with solar_state.session() as store:
        task_id = queued(store, recurring="true")
        store.task_claim_next("w")
        store.task_set_body(task_id, store.task_get(task_id)["body"].rstrip() + "\n\n" + results)
        store.task_complete(task_id)
        store.task_unset(task_id, "approved_digest")
        store.task_unset(task_id, "approved_definition")
        assert "definition_snapshot" in fm(store, task_id)
        for number in (1, 2):
            store.task_update(task_id, expected_row_version=store.task_get(task_id)["row_version"],
                              allowed_status=("draft", "planned", "queued"),
                              definition=f"\n# T\n\nNew {number}.\n")
            assert results.strip() in store.task_get(task_id)["body"]
