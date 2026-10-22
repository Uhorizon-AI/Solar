"""A question task: a prompt, one client and an optional folder. No commit, no review profile, and no
`task.authorize_run` while the client starts inside the workspace. A folder outside it is the user's call:
the task waits for `task.authorize_run` like any task that is not confined."""
import json
import os

import mcp_server
import operations
import pytest
import solar_state
from mcp_helpers import run, execute, stored, search, docs


def arguments(env, folder="inside", **ask):
    path = env.workspace / "notes" if folder == "inside" else env.tmp_path / "Downloads"
    path.mkdir(exist_ok=True)
    return dict(title="Question", instructions="What does this file say?", provider="codex",
                queue=True, ask=dict(folder=str(path), **ask))


def fields(task_id):
    return {key: solar_state.value_of(rest) for key, rest in stored(task_id)["frontmatter"]}


def manifest_of(task_id):
    return json.loads(fields(task_id)["review_input_manifest"])


def claim(task_id):
    with solar_state.session() as store:
        return store.task_claim_detail(task_id, "fixture")


def test_a_question_inside_the_workspace_runs_without_authorize_run(solar_env):
    made = run("task.create", arguments(solar_env))
    assert made["status"] == "queued" and made["risk"] == "low"
    assert made["awaiting_approval"] is False
    assert claim(made["id"])["claimed"]


@pytest.mark.parametrize("provider", ["claude", "codex", "agent", "agy"])
def test_every_launchable_client_can_be_asked(solar_env, provider):
    made = run("task.create", dict(arguments(solar_env), provider=provider))
    assert made["risk"] == "low" and made["awaiting_approval"] is False


def test_a_folder_outside_the_workspace_waits_for_the_user(solar_env):
    made = run("task.create", arguments(solar_env, folder="outside"))
    assert made["risk"] == "high" and made["awaiting_approval"] is True
    assert claim(made["id"])["reason"] == "awaiting_approval"
    run("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]))
    assert claim(made["id"])["claimed"]


@pytest.mark.parametrize("where", ["/", "home", "parent"])
def test_broad_folders_wait_for_the_user(solar_env, where):
    folder = {"/": "/", "home": os.path.expanduser("~"), "parent": str(solar_env.workspace.parent)}[where]
    args = arguments(solar_env)
    args["ask"]["folder"] = folder
    made = run("task.create", args)
    assert made["risk"] == "high" and made["awaiting_approval"] is True


def test_the_effective_folder_is_stored_and_is_the_workspace_by_default(solar_env):
    args = arguments(solar_env)
    args["ask"] = {}
    made = run("task.create", args)
    user = json.loads(manifest_of(made["id"])["user_prompt"])
    assert user["cwd"] == str(solar_env.workspace)
    access = solar_state.parse_access_policy(fields(made["id"])["access_policy"])
    assert access["mode"] == "read" and access["scopes"] == [str(solar_env.workspace)]
    assert made["risk"] == "low"


def test_the_question_is_stored_as_an_immutable_input(solar_env):
    made = run("task.create", arguments(solar_env, model="m-1"))
    values = fields(made["id"])
    assert values["execution_profile"] == "ask_readonly_v1"
    manifest = manifest_of(made["id"])
    assert manifest["provider"] == "codex" and manifest["model"] == "m-1"
    assert json.loads(manifest["user_prompt"])["instructions"] == "What does this file say?"


def test_the_start_folder_must_be_inside_a_declared_scope(solar_env, tmp_path):
    args = arguments(solar_env)
    args["access_policy"] = dict(mode="read", scopes=[str(tmp_path / "elsewhere")])
    body, error = execute("task.create", args)
    assert error and body["code"] == "review_input_invalid"
    args = arguments(solar_env)
    args["ask"] = {}
    args["access_policy"] = dict(mode="read", scopes=[str(tmp_path / "elsewhere")])
    body, error = execute("task.create", args)
    assert error and body["code"] == "review_input_invalid"


def test_editing_the_question_withdraws_the_approval(solar_env):
    made = run("task.create", arguments(solar_env))
    current = stored(made["id"])
    run("task.update", dict(task_id=made["id"], expected_row_version=current["row_version"],
                            instructions="Something else entirely.", provider="codex",
                            ask=dict(folder=str(solar_env.workspace / "notes"))))
    assert stored(made["id"])["status"] == "draft"


def test_updating_only_the_ask_says_what_is_missing(solar_env):
    made = run("task.create", arguments(solar_env))
    current = stored(made["id"])
    body, error = execute("task.update", dict(task_id=made["id"], expected_row_version=current["row_version"],
                                              ask=dict(model="m-2")))
    assert error and body["code"] == "review_input_invalid"
    assert "provider" in body["error"] and "instructions" in body["error"]


@pytest.mark.parametrize("change", ["write", "ollama", "model", "relative", "missing", "review", "batch"])
def test_an_invalid_question_creates_nothing(solar_env, tmp_path, change):
    args = arguments(solar_env)
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
    elif change == "review":
        args["review"] = dict(profile="text_only_review_v1")
    else:
        args.update(object="o", scope="s", effect="e",
                    review_batch=dict(repository=str(tmp_path), commit="0" * 40, reviews=[
                        dict(key="a", title="A", instructions="x", provider="claude")]))
    body, error = execute("task.create", args)
    assert error and body["code"] in ("review_input_invalid", "invalid_arguments"), body
    with solar_state.read_session() as store:
        assert store.task_list() == []


def test_a_question_cannot_replace_a_review_batch(solar_env, tmp_path):
    from git_review_fixture import repository
    root, commit = repository(tmp_path)
    parent = run("task.create", dict(
        title="Builder", instructions="Declare reviewers.", provider="claude", object=str(root),
        scope="Review", effect="One synthesis",
        review_batch=dict(repository=str(root), commit=commit, reviews=[
            dict(key="r1", title="R1", instructions="Check.", provider="claude")])))
    current = stored(parent["id"])
    body, error = execute("task.update", dict(task_id=parent["id"], expected_row_version=current["row_version"],
                                              instructions="A question.", provider="codex",
                                              ask=dict(folder=str(solar_env.workspace))))
    assert error and body["code"] == "review_input_invalid"
    assert stored(parent["id"])["status"] == current["status"]


def test_a_question_needs_an_explicit_client(solar_env):
    args = arguments(solar_env)
    args.pop("provider")
    body, error = execute("task.create", args)
    assert error and body["code"] == "review_input_invalid"


def test_the_detail_says_it_is_low_risk(solar_env):
    made = run("task.create", arguments(solar_env))
    detail = search(scope="tasks", task_id=made["id"], view="detail")
    assert detail["risk"] == "low" and detail["awaiting_approval"] is False


def test_a_task_that_writes_still_waits_for_authorize_run(solar_env):
    made = run("task.create", dict(title="Write", instructions="Edit files.", provider="codex", queue=True))
    assert made["risk"] == "high" and made["awaiting_approval"] is True


@pytest.mark.parametrize("language", ["en", "es"])
def test_the_confirmation_shows_the_start_folder(solar_env, language):
    import approval_text
    args = arguments(solar_env, folder="outside", model="m-1")
    folder = args["ask"]["folder"]
    assert folder in approval_text.render("task.create", args, seconds=120, lang=language)[0]
    made = run("task.create", args)
    text = approval_text.render("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]),
                                seconds=120, lang=language)[0]
    assert folder in text and "m-1" in text


def test_a_question_cannot_be_mixed_with_a_valid_review_batch(solar_env, tmp_path):
    from git_review_fixture import repository
    root, commit = repository(tmp_path)
    args = arguments(solar_env)
    args.update(object=str(root), scope="Review", effect="One synthesis",
                review_batch=dict(repository=str(root), commit=commit, reviews=[
                    dict(key="r1", title="R1", instructions="Check.", provider="claude")]))
    body, error = execute("task.create", args)
    assert error and body["code"] == "review_input_invalid", body
    with solar_state.read_session() as store:
        assert store.task_list() == []


def test_two_questions_do_not_run_at_the_same_time(solar_env):
    first = run("task.create", arguments(solar_env))
    second = run("task.create", dict(arguments(solar_env), title="Second"))
    assert claim(first["id"])["claimed"]
    assert not claim(second["id"])["claimed"]


def test_without_a_known_workspace_a_question_is_not_low_risk(solar_env, monkeypatch):
    made = run("task.create", arguments(solar_env))
    pairs = stored(made["id"])["frontmatter"]
    assert solar_state.run_risk(pairs) == "low"
    monkeypatch.delenv("SOLAR_WORKSPACE")
    assert solar_state.run_risk(pairs) == "high"


def test_the_tool_descriptions_say_how_to_ask_a_client():
    """An AI with no context must find the way from the descriptions alone, without a shell command."""
    text = mcp_server.TOOLS["solar_execute"]["description"]
    for needle in ("task.create with ask", "task.wait", "codex", "claude", "agy (Antigravity)", "agent (Cursor)",
                   "provider and instructions", "review_input_invalid", "runs alone"):
        assert needle in text, needle
    summary = operations.OPERATIONS["task.create"].summary
    assert "With ask" in summary and "agent (Cursor)" in summary


def test_the_description_points_to_a_contract_that_resolves(solar_env):
    assert docs(id="operation:task.create")["id"] == "operation:task.create"


def test_the_descriptions_say_that_only_ask_makes_a_read_only_question(solar_env):
    """Without ask a task is neither a question nor read-only; an AI must not have to guess it."""
    summary = operations.OPERATIONS["task.create"].summary
    tool = mcp_server.TOOLS["solar_execute"]["description"]
    assert "Without ask" in summary and "its read-only mode" in summary
    assert "ask is what makes it a question" in tool and "its read-only mode" in tool
    described = docs(id="operation:task.create")["arguments"]["properties"]["ask"]["description"]
    assert "its read-only mode" in described and "Without ask" in described and "Pass {}" in described


def test_an_empty_ask_is_a_question_in_the_workspace(solar_env):
    args = arguments(solar_env)
    args["ask"] = {}
    made = run("task.create", args)
    assert made["status"] == "queued" and made["risk"] == "low" and made["awaiting_approval"] is False
