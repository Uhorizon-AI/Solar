"""A question task: a prompt, one client and an optional folder. No commit, no profile of the
caller's own, and no `task.authorize_run`: the order to the harness is the permission."""
import json

import pytest
import solar_state
from mcp_helpers import run, execute, stored, search


def arguments(tmp_path, **ask):
    folder = tmp_path / "Downloads"
    folder.mkdir(exist_ok=True)
    return dict(title="Question", instructions="What does this file say?", provider="codex",
                queue=True, ask=dict(folder=str(folder), **ask))


def fields(task_id):
    return {key: solar_state.value_of(rest) for key, rest in stored(task_id)["frontmatter"]}


def test_a_question_is_queued_and_claimable_without_authorize_run(solar_env, tmp_path):
    made = run("task.create", arguments(tmp_path))
    assert made["status"] == "queued" and made["risk"] == "low"
    assert made["awaiting_approval"] is False
    with solar_state.session() as store:
        assert store.task_claim_detail(made["id"], "fixture")["claimed"]


@pytest.mark.parametrize("provider", ["claude", "codex", "agent", "agy"])
def test_every_launchable_client_can_be_asked(solar_env, tmp_path, provider):
    made = run("task.create", dict(arguments(tmp_path), provider=provider))
    assert made["risk"] == "low" and made["awaiting_approval"] is False


def test_the_question_is_stored_as_an_immutable_input(solar_env, tmp_path):
    made = run("task.create", arguments(tmp_path, model="m-1"))
    values = fields(made["id"])
    assert values["execution_profile"] == "ask_readonly_v1"
    manifest = json.loads(values["review_input_manifest"])
    assert manifest["provider"] == "codex" and manifest["model"] == "m-1"
    assert json.loads(manifest["user_prompt"])["instructions"] == "What does this file say?"
    access = solar_state.parse_access_policy(values["access_policy"])
    assert access["mode"] == "read" and access["scopes"] == [str(tmp_path / "Downloads")]


def test_no_folder_means_no_extra_scope_beyond_the_workspace(solar_env, tmp_path):
    args = arguments(tmp_path)
    args["ask"] = {}
    made = run("task.create", args)
    assert made["risk"] == "low"
    assert json.loads(json.loads(fields(made["id"])["review_input_manifest"])["user_prompt"])["cwd"] is None


def test_editing_the_question_withdraws_the_approval(solar_env, tmp_path):
    made = run("task.create", arguments(tmp_path))
    current = stored(made["id"])
    run("task.update", dict(task_id=made["id"], expected_row_version=current["row_version"],
                            instructions="Something else entirely.",
                            provider="codex", ask=dict(folder=str(tmp_path / "Downloads"))))
    task = stored(made["id"])
    assert task["status"] == "draft"


@pytest.mark.parametrize("change", ["write", "ollama", "model", "relative", "missing", "review"])
def test_an_invalid_question_creates_nothing(solar_env, tmp_path, change):
    args = arguments(tmp_path)
    if change == "write":
        args["access_policy"] = dict(mode="write", scopes=[str(tmp_path)])
    elif change == "ollama":
        args["provider"] = "ollama"
    elif change == "model":
        args["ask"]["model"] = "-unsafe"
    elif change == "relative":
        args["ask"]["folder"] = "Downloads"
    elif change == "missing":
        args["ask"]["folder"] = str(tmp_path / "not-there")
    else:
        args["review"] = dict(profile="text_only_review_v1")
    body, error = execute("task.create", args)
    assert error and body["code"] in ("review_input_invalid", "invalid_arguments"), body
    with solar_state.read_session() as store:
        assert store.task_list() == []


def test_a_question_needs_an_explicit_client(solar_env, tmp_path):
    args = arguments(tmp_path)
    args.pop("provider")
    body, error = execute("task.create", args)
    assert error and body["code"] == "review_input_invalid"


def test_the_detail_says_it_is_low_risk(solar_env, tmp_path):
    made = run("task.create", arguments(tmp_path))
    detail = search(scope="tasks", task_id=made["id"], view="detail")
    assert detail["risk"] == "low" and detail["awaiting_approval"] is False


def test_a_task_that_writes_still_waits_for_authorize_run(solar_env):
    made = run("task.create", dict(title="Write", instructions="Edit files.", provider="codex", queue=True))
    assert made["risk"] == "high" and made["awaiting_approval"] is True
