"""A question task: a prompt, one client and an optional folder. No commit, no review profile, and no
`task.authorize_run` while the client starts inside the workspace. A folder outside it is the user's call:
the task waits for `task.authorize_run` like any task that is not confined."""
import json
import os
import pathlib

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


def test_the_descriptions_say_what_makes_a_read_only_question(solar_env):
    """An AI must not have to guess it: ask, or a declared read with a client and a prompt."""
    summary = operations.OPERATIONS["task.create"].summary
    tool = mcp_server.TOOLS["solar_execute"]["description"]
    assert "With ask" in summary and "its read-only mode" in summary and "declared read" in summary
    assert "declared read" in tool and "its read-only mode" in tool
    described = docs(id="operation:task.create")["arguments"]["properties"]["ask"]["description"]
    assert "its read-only mode" in described and "declared read" in described and "Pass {}" in described


def test_an_empty_ask_is_a_question_in_the_workspace(solar_env):
    args = arguments(solar_env)
    args["ask"] = {}
    made = run("task.create", args)
    assert made["status"] == "queued" and made["risk"] == "low" and made["awaiting_approval"] is False


def test_the_descriptions_keep_ask_for_own_content_and_send_external_content_to_the_cage(solar_env):
    """Read-only is a request: external content must not be given to ask."""
    summary = operations.OPERATIONS["task.create"].summary
    assert "own content" in summary and "external" in summary and "goes through review with profile" in summary
    assert "repository_readonly_v1" in summary
    described = docs(id="operation:task.create")["arguments"]["properties"]["ask"]["description"]
    assert "own content" in described and "goes through review with profile repository_readonly_v1" in described


def test_the_guide_says_which_content_may_go_to_ask():
    guide = (pathlib.Path(__file__).resolve().parents[3] / "docs" / "repository-readonly-review.md").read_text()
    section = guide.split("## Questions (`ask_readonly_v1`)", 1)[1].split("\n## ", 1)[0]
    assert "**Own content only.**" in section and "external" in section and "repository_readonly_v1" in section


def test_the_response_shows_the_zone_as_declared_and_not_verified(solar_env):
    inside = run("task.create", arguments(solar_env))
    assert inside["zone"]["zone"] == "workspace" and inside["zone"]["verified"] is False
    assert inside["zone"]["note"] == "declared, not verified"
    outside = run("task.create", arguments(solar_env, folder="outside"))
    assert outside["zone"]["zone"] == "outside"
    assert outside["zone"]["paths"][0]["path"] == str(solar_env.tmp_path / "Downloads")


def test_a_task_without_declared_access_shows_no_zone(solar_env):
    made = run("task.create", dict(title="Write", instructions="Edit files.", provider="codex", queue=True))
    assert "zone" not in made


def test_showing_the_zone_changes_nobody_s_wait(solar_env):
    inside = run("task.create", arguments(solar_env))
    outside = run("task.create", arguments(solar_env, folder="outside"))
    assert (inside["risk"], inside["awaiting_approval"]) == ("low", False)
    assert (outside["risk"], outside["awaiting_approval"]) == ("high", True)


def test_mixed_declared_paths_show_the_outermost_and_each_path(solar_env):
    args = arguments(solar_env)
    mixed = [str(solar_env.workspace / "notes"), str(solar_env.tmp_path)]
    args["access_policy"] = dict(mode="read", scopes=mixed, resources=[])
    args["ask"] = dict(folder=str(solar_env.workspace / "notes"))
    made = run("task.create", args)
    assert made["zone"]["zone"] == "outside"
    assert [item["zone"] for item in made["zone"]["paths"]] == ["workspace", "outside"]


@pytest.mark.parametrize("language,label,note", [("en", "Path zone", "declared, not verified"),
                                                 ("es", "Zona de la ruta", "declarada, no verificada")])
def test_the_confirmation_shows_the_zone_as_declared(solar_env, language, label, note):
    import approval_text
    text = approval_text.render("task.create", arguments(solar_env, folder="outside"), seconds=120, lang=language)[0]
    assert label in text and "outside" in text and note in text


def derived(env, scopes, **extra):
    """The same question without `ask`: only a declared read, a client and a prompt."""
    return dict(title="Question", instructions="What does this file say?", provider="codex", queue=True,
                access_policy=dict(mode="read", scopes=scopes, resources=[]), **extra)


def same_configuration(first, second):
    one, two = fields(first), fields(second)
    for key in ("execution_profile", "review_input_manifest", "review_input_digest", "access_policy"):
        assert one[key] == two[key], key


def test_a_declared_read_gets_the_same_profile_and_fingerprint_as_ask(solar_env):
    workspace = str(solar_env.workspace)
    by_ask = run("task.create", dict(arguments(solar_env), ask={}, access_policy=dict(
        mode="read", scopes=[workspace], resources=[])))
    by_read = run("task.create", derived(solar_env, [workspace]))
    same_configuration(by_ask["id"], by_read["id"])
    assert by_read["risk"] == "low" and by_read["awaiting_approval"] is False


def test_the_alias_keeps_an_explicit_declaration_whole(solar_env):
    workspace, notes = str(solar_env.workspace), str(solar_env.workspace / "notes")
    (solar_env.workspace / "notes").mkdir(exist_ok=True)
    access = dict(mode="read", scopes=[workspace, notes], resources=[])
    by_ask = run("task.create", dict(arguments(solar_env), ask={}, access_policy=access))
    by_read = run("task.create", dict(derived(solar_env, [workspace]), access_policy=access))
    same_configuration(by_ask["id"], by_read["id"])
    stored = solar_state.parse_access_policy(fields(by_read["id"])["access_policy"])
    assert stored["scopes"] == sorted([workspace, notes])
    held = run("task.create", dict(arguments(solar_env), ask={}, access_policy=dict(
        mode="read", scopes=[workspace], resources=["browser"])))
    assert solar_state.parse_access_policy(fields(held["id"])["access_policy"])["resources"] == ["browser"]


def test_declaring_only_a_planet_without_the_workspace_is_refused_like_ask(solar_env):
    planet = solar_env.workspace / "planets" / "acme"
    planet.mkdir(parents=True)
    body, error = execute("task.create", derived(solar_env, [str(planet)]))
    assert error and body["code"] == "review_input_invalid" and "ask.folder" in json.dumps(body), body
    body, error = execute("task.create", dict(arguments(solar_env), ask={}, access_policy=dict(
        mode="read", scopes=[str(planet)], resources=[])))
    assert error and body["code"] == "review_input_invalid", body


def test_a_declared_write_or_a_read_without_client_is_not_a_question(solar_env):
    workspace = str(solar_env.workspace)
    write = run("task.create", dict(derived(solar_env, [workspace]), access_policy=dict(
        mode="write", scopes=[workspace], resources=[])))
    assert "execution_profile" not in fields(write["id"]) and write["risk"] == "high"
    no_client = dict(derived(solar_env, [workspace]))
    del no_client["provider"]
    made = run("task.create", no_client)
    assert "execution_profile" not in fields(made["id"])


@pytest.mark.parametrize("through", ["ask", "declared read"])
def test_a_declared_path_outside_the_workspace_waits_even_when_it_starts_inside(solar_env, through):
    workspace, outside = str(solar_env.workspace), str(solar_env.tmp_path / "Downloads")
    (solar_env.tmp_path / "Downloads").mkdir(exist_ok=True)
    scopes = [workspace, outside]
    if through == "ask":
        args = dict(arguments(solar_env), ask={}, access_policy=dict(mode="read", scopes=scopes, resources=[]))
    else:
        args = derived(solar_env, scopes)
    made = run("task.create", args)
    assert made["risk"] == "high" and made["awaiting_approval"] is True
    assert made["zone"]["zone"] == "outside"


def test_editing_a_question_refreshes_its_inputs_and_keeps_its_folder_and_model(solar_env):
    made = run("task.create", dict(arguments(solar_env, model="m-1"), queue=False))
    folder = json.loads(manifest_of(made["id"])["user_prompt"])["cwd"]
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                            instructions="A different question?"))
    after = manifest_of(made["id"])
    assert json.loads(after["user_prompt"]) == dict(instructions="A different question?", cwd=folder)
    assert after["model"] == "m-1"
    fresh = run("task.create", dict(arguments(solar_env, model="m-1"), queue=False,
                                    instructions="A different question?"))
    assert fields(made["id"])["review_input_digest"] == fields(fresh["id"])["review_input_digest"]


def test_a_read_with_exclusive_resources_is_not_derived(solar_env):
    workspace = str(solar_env.workspace)
    held = run("task.create", dict(derived(solar_env, [workspace]), access_policy=dict(
        mode="read", scopes=[workspace], resources=["browser"])))
    assert "execution_profile" not in fields(held["id"]) and held["risk"] == "high"


def test_an_unsupported_client_is_refused_for_a_derived_read(solar_env):
    body, error = execute("task.create", dict(derived(solar_env, [str(solar_env.workspace)]), provider="gemini"))
    assert error, body


def test_a_revision_never_becomes_a_question_by_derivation(solar_env):
    workspace = str(solar_env.workspace)
    plain = run("task.create", dict(title="Plain", instructions="Do it.", provider="codex", queue=False))
    revised = run("task.create", dict(derived(solar_env, [workspace]), queue=False, revises_task_id=plain["id"]))
    assert "execution_profile" not in fields(revised["id"])
    question = run("task.create", dict(arguments(solar_env), queue=False))
    again = run("task.create", dict(derived(solar_env, [workspace]), queue=False, revises_task_id=question["id"]))
    assert fields(again["id"])["execution_profile"] == fields(question["id"])["execution_profile"]


def test_a_path_that_changes_meaning_when_normalized_is_refused(solar_env):
    workspace = solar_env.workspace
    outside = solar_env.tmp_path / "elsewhere" / "child"
    outside.mkdir(parents=True)
    os.symlink(outside, workspace / "link")
    sneaky = str(workspace / "link" / ".." / "secret")
    body, error = execute("task.create", derived(solar_env, [str(workspace), sneaky]))
    assert error and body["code"] == "review_input_invalid", body


def test_mixed_paths_with_a_folder_outside_wait_and_say_outside(solar_env):
    workspace = str(solar_env.workspace)
    install = solar_env.tmp_path / "home" / ".local" / "share" / "solar"
    install.mkdir(parents=True)
    made = run("task.create", derived(solar_env, [workspace, str(install)]))
    assert made["zone"]["zone"] == "outside" and made["risk"] == "high" and made["awaiting_approval"] is True


def test_a_planet_linked_outside_the_workspace_is_outside_and_waits(solar_env):
    target = solar_env.tmp_path / "elsewhere"
    target.mkdir(exist_ok=True)
    (solar_env.workspace / "planets").mkdir(exist_ok=True)
    os.symlink(target, solar_env.workspace / "planets" / "linked")
    made = run("task.create", derived(solar_env, [str(solar_env.workspace), str(solar_env.workspace / "planets" / "linked")]))
    assert made["zone"]["zone"] == "outside" and made["risk"] == "high"


def test_the_start_folder_and_declared_paths_use_the_same_containment_as_the_zone(solar_env):
    workspace = solar_env.workspace
    upper = pathlib.Path(str(workspace).upper())
    same_folder = upper.exists() and os.path.samefile(upper, workspace)
    made = run("task.create", dict(arguments(solar_env), ask={}, access_policy=dict(
        mode="read", scopes=[str(workspace), str(upper)], resources=[])))
    # the disk decides: the upper-case spelling is the workspace itself, or another folder that waits
    assert (made["zone"]["zone"], made["risk"]) == (("workspace", "low") if same_folder else ("outside", "high"))


def test_an_empty_ask_is_listed_in_the_confirmation(solar_env):
    import approval_text
    text = approval_text.render("task.create", dict(arguments(solar_env), ask={}), seconds=120, lang="en")[0]
    assert "ask_readonly_v1" in text


def test_editing_the_access_of_a_question_re_derives_and_can_make_it_wait(solar_env):
    made = run("task.create", dict(arguments(solar_env), queue=False))
    outside = solar_env.tmp_path / "Downloads"
    outside.mkdir(exist_ok=True)
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"],
                            access_policy=dict(mode="read", scopes=[str(solar_env.workspace / "notes"), str(outside)])))
    queued = run("task.approve", dict(task_id=made["id"], expected_row_version=stored(made["id"])["row_version"]))
    assert search(scope="tasks", task_id=made["id"], view="detail")["risk"] == "high"


def test_a_sneaky_start_folder_waits_when_it_exists_and_is_refused_when_it_does_not(solar_env):
    workspace = solar_env.workspace
    outside = solar_env.tmp_path / "elsewhere" / "child"
    outside.mkdir(parents=True)
    (outside.parent / "secret").mkdir()
    (workspace / "secret").mkdir(exist_ok=True)
    os.symlink(outside, workspace / "hop")
    args = arguments(solar_env)
    args["ask"] = dict(folder=str(workspace / "hop" / ".." / "secret"))
    made = run("task.create", args)   # the real folder is outside the workspace: it waits for the user
    assert made["risk"] == "high" and made["awaiting_approval"] is True and made["zone"]["zone"] == "outside"
    args["ask"] = dict(folder=str(workspace / "hop" / ".." / "missing"))
    body, error = execute("task.create", args)   # it does not exist: refused outright
    assert error and body["code"] == "review_input_invalid", body


@pytest.mark.parametrize("language,label", [("en", "Path zone"), ("es", "Zona de la ruta")])
def test_authorizing_a_question_shows_its_declared_zone(solar_env, language, label):
    import approval_text
    made = run("task.create", arguments(solar_env, folder="outside"))
    text = approval_text.render("task.authorize_run", dict(task_id=made["id"], expected_row_version=made["row_version"]),
                                seconds=120, lang=language)[0]
    assert label in text and "outside" in text and ("declared, not verified" in text or "declarada, no verificada" in text)


def test_the_ask_schema_says_every_declared_path_counts(solar_env):
    described = docs(id="operation:task.create")["arguments"]["properties"]["ask"]["description"]
    assert "every declared path" in described


@pytest.mark.parametrize("language,fragment", [("en", "read-only is a request to the client"),
                                               ("es", "solo lectura es una petición al cliente")])
def test_the_confirmation_says_that_read_only_is_a_request(solar_env, language, fragment):
    import approval_text
    args = arguments(solar_env)
    assert fragment in approval_text.render("task.create", args, seconds=120, lang=language)[0]
    made = run("task.create", args)
    text = approval_text.render("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"]),
                                seconds=120, lang=language)[0]
    assert fragment in text


def test_the_descriptions_say_that_a_clients_settings_can_still_allow_writes(solar_env):
    schema = operations.OPERATIONS["task.create"].summary
    assert "Codex with on-request approvals" in schema
    assert "Codex with on-request approvals" in operations._ASK["description"]
