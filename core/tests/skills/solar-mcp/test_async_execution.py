"""async_execution.propose / apply and the access declaration of task.create / task.update."""
from __future__ import annotations

import json

import pytest

import mcp_approve
import mcp_server
import solar_state
from mcp_helpers import execute, new_task, run, search, stored


class _EveryProvider:
    def __contains__(self, _):
        return True


@pytest.fixture(autouse=True)
def verified_profile(monkeypatch):
    """Stands in for a verified implementation of the profile (none exists yet)."""
    monkeypatch.setattr(solar_state, "VERIFIED_PROFILES", {"text_only_review_v1": _EveryProvider()})


def refuse(operation, arguments, code):
    body, error = execute(operation, arguments)
    assert error, body
    assert body.get("code") == code, body
    return body


def applied():
    with solar_state.session() as store:
        return store.async_policy()


def proposal_path():
    with solar_state.session() as store:
        return solar_state.config_path(store.root)


# --------------------------------------------------------------------------
# registration and authority
# --------------------------------------------------------------------------

def test_the_operations_are_registered_with_a2_authority(solar_env):
    names = {r["name"] for r in search(scope="operations", query="async_execution")["operations"]}
    assert names == {"async_execution.propose", "async_execution.apply"}
    for name in names:
        assert mcp_server.operations.OPERATIONS[name].authority == "A2"


def test_neither_operation_runs_without_a_granted_approval(solar_env):
    for operation, arguments in (("async_execution.propose", dict(global_capacity=3)),
                                 ("async_execution.apply", dict(revision=1, proposal_digest="0" * 64))):
        body, error = execute(operation, arguments, approved=False)
        assert error and body.get("code") != "ok"
    assert applied()["global_capacity"] == 1 and not proposal_path().exists()


def test_an_approval_is_bound_to_the_exact_revision_and_digest(solar_env):
    proposed = run("async_execution.propose", dict(global_capacity=3))
    grant = mcp_approve.grant("async_execution.apply", dict(revision=proposed["revision"],
                                                            proposal_digest=proposed["proposal_digest"]), 900, "t")
    body, error = mcp_server.call_tool("solar_execute", dict(
        operation="async_execution.apply", approval_id=grant["approval_id"],
        arguments=dict(revision=proposed["revision"], proposal_digest="f" * 64)))
    assert error, body
    assert applied()["global_capacity"] == 1


@pytest.mark.parametrize("arguments", [
    dict(global_capacity=6), dict(global_capacity=0), dict(global_capacity=True),
    dict(global_capacity=2, extra=1), dict(global_capacity=2, provider_limits=[dict(provider="codex", limit=9)]),
    dict(global_capacity=2, exclusive_wait_seconds=0), dict(global_capacity=2, enabled_reader_profiles="x"),
])
def test_propose_validates_its_arguments(solar_env, arguments):
    body, error = execute("async_execution.propose", arguments)
    assert error and body["code"] == "invalid_arguments"
    assert not proposal_path().exists()


# --------------------------------------------------------------------------
# propose then apply
# --------------------------------------------------------------------------

def test_propose_writes_the_file_and_changes_nothing(solar_env):
    out = run("async_execution.propose", dict(
        global_capacity=3, provider_limits=[dict(provider="codex", limit=2)],
        exclusive_wait_seconds=45, enabled_reader_profiles=["text_only_review_v1"]))
    assert out["proposed"] and out["applied"] is False and out["revision"] == 1
    document = json.loads(proposal_path().read_text())
    assert document == dict(schema_version=1, revision=1, global_capacity=3,
                            provider_capacity={"codex": 2}, exclusive_wait_seconds=45,
                            enabled_reader_profiles=["text_only_review_v1"])
    assert out["proposal_digest"] == solar_state.policy_digest(document)
    assert applied()["global_capacity"] == 1 and applied()["revision"] == 0       # still the initial policy


def test_apply_makes_the_revision_the_one_every_claim_reads(solar_env):
    proposed = run("async_execution.propose", dict(global_capacity=3, provider_limits=[dict(provider="Codex", limit=2)],
                                                   enabled_reader_profiles=["text_only_review_v1"]))
    done = run("async_execution.apply", dict(revision=proposed["revision"],
                                             proposal_digest=proposed["proposal_digest"]))
    assert done["applied"] and done["global_capacity"] == 3 and done["provider_capacity"] == {"codex": 2}
    assert applied()["revision"] == 1 and applied()["applied_by"] == "mcp:async_execution.apply"
    with solar_state.session() as store:
        ids = [store.task_create([("title", f'"T{i}"'), ("execution_profile", "text_only_review_v1"),
                                  ("access_policy", json.dumps(dict(version=1, mode="read", scopes=[], resources=[])))],
                                 "\n# T\n", status="queued") for i in range(4)]
        assert [store.task_claim_detail(t, "w")["claimed"] for t in ids] == [True, True, True, False]
        assert store.async_policy()["provider_capacity"] == {"codex": 2}          # kept in lowercase


def test_editing_the_file_by_hand_activates_nothing(solar_env):
    proposed = run("async_execution.propose", dict(global_capacity=2))
    path = proposal_path()
    path.write_text(json.dumps(dict(schema_version=1, revision=1, global_capacity=5)), encoding="utf-8")
    assert applied()["global_capacity"] == 1
    refuse("async_execution.apply", dict(revision=1, proposal_digest=proposed["proposal_digest"]),
           "proposal_changed")                       # the approval named other content
    assert applied()["global_capacity"] == 1


def test_apply_without_a_file_or_with_another_revision_is_refused(solar_env):
    refuse("async_execution.apply", dict(revision=1, proposal_digest="a" * 64), "proposal_missing")
    proposed = run("async_execution.propose", dict(global_capacity=2))
    refuse("async_execution.apply", dict(revision=2, proposal_digest=proposed["proposal_digest"]),
           "proposal_changed")


def test_an_invalid_file_is_rejected_and_the_previous_revision_stays(solar_env):
    first = run("async_execution.propose", dict(global_capacity=4))
    run("async_execution.apply", dict(revision=1, proposal_digest=first["proposal_digest"]))
    path = proposal_path()
    broken = dict(schema_version=1, revision=2, global_capacity=9)
    path.write_text(json.dumps(broken), encoding="utf-8")
    digest = solar_state.policy_digest(broken)
    refuse("async_execution.apply", dict(revision=2, proposal_digest=digest), "policy_invalid")
    assert applied()["global_capacity"] == 4 and applied()["revision"] == 1
    path.write_text("{ not json", encoding="utf-8")
    refuse("async_execution.apply", dict(revision=2, proposal_digest=digest), "proposal_changed")
    assert applied()["revision"] == 1


def test_a_revision_cannot_be_applied_twice_and_the_next_one_keeps_what_it_does_not_name(solar_env):
    first = run("async_execution.propose", dict(global_capacity=3, provider_limits=[dict(provider="codex", limit=2)],
                                                exclusive_wait_seconds=30))
    run("async_execution.apply", dict(revision=1, proposal_digest=first["proposal_digest"]))
    refuse("async_execution.apply", dict(revision=1, proposal_digest=first["proposal_digest"]), "policy_invalid")
    second = run("async_execution.propose", dict(global_capacity=2))
    assert second["revision"] == 2
    document = json.loads(proposal_path().read_text())
    assert document["provider_capacity"] == {"codex": 2} and document["exclusive_wait_seconds"] == 30
    run("async_execution.apply", dict(revision=2, proposal_digest=second["proposal_digest"]))
    assert applied()["global_capacity"] == 2


def test_a_validation_message_that_mentions_a_digest_is_not_a_changed_proposal(solar_env):
    broken = dict(schema_version=1, revision=1, global_capacity=2, provider_capacity={"digest": 9})
    path = proposal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(broken), encoding="utf-8")
    refuse("async_execution.apply", dict(revision=1, proposal_digest=solar_state.policy_digest(broken)),
           "policy_invalid")
    assert applied()["revision"] == 0


def test_the_proposal_lives_under_the_resolved_runtime(solar_env):
    run("async_execution.propose", dict(global_capacity=2))
    with solar_state.session() as store:
        assert proposal_path() == store.root / "async-tasks" / "config" / "async-execution.json"
    assert proposal_path().is_file()


def test_the_confirmation_text_shows_the_change(solar_env):
    import approval_text
    message, _title = approval_text.render("async_execution.propose", dict(global_capacity=3), seconds=60, lang="en")
    assert "1 → 3" in message and "Nothing changes until it is applied" in message
    run("async_execution.propose", dict(global_capacity=3))
    message, _title = approval_text.render("async_execution.apply", dict(
        revision=1, proposal_digest="a" * 64), seconds=60, lang="en")
    assert "0 → 1" in message and "1 → 3" in message and "never stopped" in message
    spanish, _ = approval_text.render("async_execution.apply", dict(revision=1, proposal_digest="a" * 64),
                                      seconds=60, lang="es")
    assert "Tareas simultáneas" in spanish


# --------------------------------------------------------------------------
# the access declaration of a task
# --------------------------------------------------------------------------

def test_create_stores_the_declaration_in_canonical_form(solar_env):
    made = new_task("Reader", access_policy=dict(mode="read", scopes=["/b", "/a/"], resources=["z", "y"]))
    values = {k: solar_state.value_of(v) for k, v in stored(made["id"])["frontmatter"]}
    assert values["access_policy"] == '{"mode":"read","resources":["y","z"],"scopes":["/a","/b"],"version":1}'


def test_a_task_without_a_declaration_stays_legacy(solar_env):
    made = new_task("Plain")
    assert "access_policy" not in dict(stored(made["id"])["frontmatter"])


@pytest.mark.parametrize("policy", [dict(mode="write"), dict(mode="write", scopes=["rel/path"]),
                                    dict(mode="read", scopes=["/a", "/a"])])
def test_an_invalid_declaration_is_refused(solar_env, policy):
    body, error = execute("task.create", dict(title="T", instructions="x", access_policy=policy))
    assert error and body["code"] in ("access_policy_invalid", "invalid_arguments")


def test_unknown_keys_and_modes_are_not_accepted(solar_env):
    for policy in (dict(mode="exec"), dict(mode="read", other=1), dict()):
        body, error = execute("task.create", dict(title="T", instructions="x", access_policy=policy))
        assert error and body["code"] == "invalid_arguments"


def test_changing_the_declaration_of_a_queued_task_withdraws_its_approval(solar_env):
    made = new_task("Reader", access_policy=dict(mode="read", scopes=["/a"]))
    run("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    version = stored(made["id"])["row_version"]
    same = run("task.update", dict(task_id=made["id"], expected_row_version=version,
                                   access_policy=dict(mode="read", scopes=["/a/"])))
    assert same["status"] == "queued"                  # the same declaration in another spelling
    out = run("task.update", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"],
                                  access_policy=dict(mode="write", scopes=["/a"])))
    assert out["status"] == "draft" and out["approval_withdrawn"] is True


def test_a_revision_keeps_the_access_of_its_source(solar_env):
    made = new_task("Reader", access_policy=dict(mode="read", scopes=["/a"]))
    revision = run("task.create", dict(title="Reader v2", instructions="x", revises_task_id=made["id"]))
    values = {k: solar_state.value_of(v) for k, v in stored(revision["id"])["frontmatter"]}
    assert json.loads(values["access_policy"])["mode"] == "read"


def test_the_approval_text_shows_what_the_task_reads_or_writes(solar_env):
    import approval_text
    created, _ = approval_text.render("task.create", dict(
        title="T", instructions="x", access_policy=dict(mode="write", scopes=["/repo/docs"], resources=["browser"])),
        seconds=60, lang="en")
    assert "Access: writes: /repo/docs; holds exclusively: browser" in created
    made = new_task("Plain")
    approving, _ = approval_text.render("task.approve", dict(
        task_id=made["id"], expected_row_version=made["row_version"]), seconds=60, lang="en")
    assert "runs alone" in approving
    updating, _ = approval_text.render("task.update", dict(
        task_id=made["id"], expected_row_version=made["row_version"],
        access_policy=dict(mode="read", scopes=["/x"])), seconds=60, lang="en")
    assert "reads: /x" in updating
