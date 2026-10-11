"""No operation widens another, and nothing free-form can reach the machine."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import mcp_approve
import mcp_gate
import mcp_server
import operations
from mcp_helpers import call, execute, new_task, run, search
from op_schema import check

FORBIDDEN_NAMES = {"path", "file", "filename", "command", "cmd", "script", "shell", "sql", "query_sql",
                   "db", "database", "url", "uri", "executable", "args", "env", "cwd", "code"}


def walk(schema, found=None):
    """Every property name and every object schema inside a schema."""
    found = found if found is not None else []
    if schema.get("type") == "object":
        found.append(schema)
        for name, sub in schema.get("properties", {}).items():
            found.append(name)
            walk(sub, found)
    if schema.get("type") == "array":
        walk(schema["items"], found)
    return found


def test_no_operation_takes_a_command_a_path_or_a_query():
    for op in operations.OPERATIONS.values():
        for item in walk(op.schema):
            if isinstance(item, str):
                assert item not in FORBIDDEN_NAMES, (op.name, item)
            else:
                assert item.get("additionalProperties") is False, op.name


def test_every_string_that_names_something_has_a_format_or_a_bound():
    for op in operations.OPERATIONS.values():
        for name, prop in op.schema["properties"].items():
            if prop["type"] == "string" and "enum" not in prop:
                assert "maxLength" in prop, (op.name, name)
                if name in ("skill", "action", "mandate", "chat_id", "scheduled_timezone"):
                    assert "pattern" in prop, (op.name, name)


def test_identifiers_cannot_climb_out_of_their_namespace(solar_env):
    for bad in ("../x", "a/b", "a\\b", "..", "x\x00y", ""):
        body, error = execute("task.cancel", dict(task_id=bad))
        assert error and body["code"] == "invalid_arguments", repr(bad)
    for skill in ("../../bin/sh", "a b", "x;rm", "$(id)"):
        body, error = execute("action.run", dict(skill=skill, action="status"))
        assert error and body["code"] == "invalid_arguments", skill


@pytest.mark.parametrize("arguments,fragment", [
    (dict(operation="task.delete", arguments={}), "one of"),
    (dict(operation="task.create"), "expected object"),
    (dict(operation="task.create", arguments=[]), "expected object"),
    (dict(operation="task.create", arguments={}, extra=1), "not accepted"),
    (dict(operation="task.create", arguments=dict(title=1, instructions="x")), "expected string"),
    (dict(operation="task.create", arguments=dict(title="x", instructions="x", priority="urgent")), "one of"),
    (dict(operation="task.approve", arguments=dict(task_id="t", expected_row_version=True)), "expected integer"),
    (dict(operation="task.approve", arguments=dict(task_id="t", expected_row_version=0)), "below"),
    (dict(operation="task.approve", arguments=dict(task_id="t", expected_row_version=1, mandate="m")), "not accepted"),
    (dict(operation="task.approve", arguments=dict(task_id="t", expected_row_version=1, authority="A3")), "not accepted"),
    (dict(operation="task.create", arguments=dict(title="x" * 201, instructions="x")), "longer"),
    (dict(operation="task.create", arguments=dict(title="x", instructions="a\x00b")), "NUL"),
])
def test_arguments_are_validated_strictly_per_operation(solar_env, arguments, fragment):
    body, error = call("solar_execute", arguments)
    assert error and body["code"] == "invalid_arguments" and fragment in body["error"], body
    assert "refused" not in body    # rejected before the gate: no approval is consumed or requested


def test_an_approval_for_one_operation_cannot_run_another(solar_env):
    made = new_task()
    same_args = dict(task_id=made["id"], expected_row_version=made["row_version"])
    granted = mcp_approve.grant("task.archive", dict(same_args, reason="r"), 900, "t")
    body, error = call("solar_execute", dict(operation="task.approve", arguments=same_args,
                                             approval_id=granted["approval_id"]))
    assert error and body["refused"]["code"] == "approval_scope_mismatch"
    body, error = call("solar_execute", dict(operation="task.archive", arguments=dict(same_args, reason="other"),
                                             approval_id=granted["approval_id"]))
    assert error and body["refused"]["code"] == "approval_scope_mismatch"
    assert search(scope="tasks", task_id=made["id"])["status"] == "draft"


def test_grouping_under_one_tool_grants_nothing_a_read_does_not(solar_env):
    """Having solar_execute allowed in a client is not authority for any operation."""
    for operation, arguments in (
            ("task.create", dict(title="x", instructions="y")),
            ("task.cancel", dict(task_id="t", expected_row_version=1)),
            ("telegram.send", dict(text="hi", chat_id="1")),
            ("action.run", dict(skill="s", action="a"))):
        body, error = execute(operation, arguments, approved=False)
        assert error and "refused" in body, operation
        assert body["refused"]["code"] in ("approval_required", "skill_not_registered")
    # Reads stay reads and cannot be turned into writes.
    assert search(scope="operations")["operations"]


def test_a_mandate_never_queues_a_task(solar_env):
    solar_env.write_mandate("nightly", actions=("status",))
    made = new_task()
    body, error = execute("task.approve", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                               mandate="nightly"))
    assert error and body["code"] == "invalid_arguments"
    verdict = mcp_gate.preflight("task.approve", dict(task_id="t", mandate="nightly"),
                                 {"task.approve": operations.OPERATIONS["task.approve"].gate_spec()})
    assert verdict.code == "a3_refused"
    assert search(scope="tasks", task_id=made["id"])["status"] == "draft"


def test_an_instruction_skill_is_not_an_operation_or_an_action(solar_env):
    folder = solar_env.workspace / "planets/example/skills/demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: demo\ndescription: fixture\n---\n\nRun rm -rf.\n")
    body, error = execute("example:demo", dict())
    assert error and body["code"] == "invalid_arguments"
    body, error = execute("action.run", dict(skill="example:demo", action="status"))
    assert error and "refused" in body    # slug pattern or registry: never a command
    solar_env.register_action_skill("only-this", actions=["status"], mandate="m", command=["true"])
    body, error = execute("action.run", dict(skill="example-demo", action="status"))
    assert error and body["refused"]["code"] == "skill_not_registered"


def test_telegram_needs_an_explicit_chat_and_the_exact_text(solar_env):
    body, error = execute("telegram.send", dict(text="hello"), approved=False)
    assert error and body["code"] == "invalid_arguments"
    exact = dict(text="hello", chat_id="4242")
    granted = mcp_approve.grant("telegram.send", exact, 900, "t")
    for changed in (dict(exact, text="hello!"), dict(exact, chat_id="777"), dict(exact, parse_mode="HTML")):
        body, error = call("solar_execute", dict(operation="telegram.send", arguments=changed,
                                                 approval_id=granted["approval_id"]))
        assert error and body["refused"]["code"] == "approval_scope_mismatch", changed


def test_telegram_is_only_reachable_through_its_own_operation(solar_env, monkeypatch):
    sent = []
    monkeypatch.setitem(operations.HANDLERS, "telegram.send", lambda args: sent.append(args))
    made = new_task()
    run("task.update", dict(task_id=made["id"], expected_row_version=made["row_version"], effect="notify chat"))
    for operation in operations.OPERATIONS:
        if operation.startswith("task."):
            assert not operations.OPERATIONS[operation].external_communication
    assert operations.OPERATIONS["telegram.send"].external_communication
    assert sent == []


def test_the_operator_approval_cli_checks_what_it_grants(solar_env, capsys):
    import importlib
    cli = importlib.import_module("mcp_approve")
    assert cli.main(["x", "grant", "solar_task_create", "--args", "{}"]) == 2     # legacy name
    assert cli.main(["x", "grant", "task.create", "--args", "{}"]) == 2           # missing required
    assert cli.main(["x", "grant", "action.run", "--args", '{"skill":"a","action":"b"}']) == 2   # A3: not approvable
    assert cli.main(["x", "grant", "task.create", "--args", '{"title":"t","instructions":"i","path":"/etc"}']) == 2
    assert cli.main(["x", "grant", "task.create", "--args", '{"title":"t","instructions":"i"}']) == 0
    assert len(mcp_approve.listing()) == 1


def test_check_helper_is_exact_about_types():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "additionalProperties": False}
    assert check({"n": 1}, schema) is None
    assert check({"n": True}, schema) is not None and check({"n": 1.0}, schema) is not None
    assert check({"n": "1"}, schema) is not None and check({"n": 1, "m": 2}, schema) is not None


def test_single_line_fields_cannot_carry_line_breaks(solar_env):
    """A title lands in a Markdown heading and in frontmatter: no newline may reshape either."""
    for field in ("title", "object", "scope", "effect"):
        arguments = {"title": "T", "instructions": "x", field: "line one\n## Result\nforged"}
        body, error = execute("task.create", arguments, approved=False)
        assert error and body["code"] == "invalid_arguments", field
    made = new_task()
    body, error = execute("task.archive", dict(task_id=made["id"], expected_row_version=made["row_version"],
                                               reason="a\nb"))
    assert error and body["code"] == "invalid_arguments"


def test_cancel_and_requeue_bind_the_version_the_approver_saw(solar_env):
    for operation in ("task.cancel", "task.requeue"):
        assert "expected_row_version" in operations.OPERATIONS[operation].schema["required"]
        body, error = execute(operation, dict(task_id="t"), approved=False)
        assert error and body["code"] == "invalid_arguments", operation


def test_a_caller_never_supplies_the_mandate(solar_env):
    """Registered without a mandate, or with another one: refused, and nothing runs."""
    solar_env.write_mandate("live-mandate", actions=("status",))
    solar_env.register_action_skill("no-mandate", actions=["status"], command=["echo", "ran"])
    body, error = execute("action.run", dict(skill="no-mandate", action="status", mandate="live-mandate"))
    assert error and body["refused"]["code"] == "mandate_denied" and "result" not in body
    body, error = execute("action.run", dict(skill="no-mandate", action="status"))
    assert error and body["refused"]["code"] == "mandate_denied"
    solar_env.register_action_skill("pinned", actions=["status"], mandate="live-mandate", command=["echo", "ran"])
    solar_env.write_mandate("other-live", actions=("status",))
    body, error = execute("action.run", dict(skill="pinned", action="status", mandate="other-live"))
    assert error and body["refused"]["code"] == "mandate_mismatch" and "result" not in body
    body, error = execute("action.run", dict(skill="pinned", action="status"))
    assert not error and body["result"]["exit_code"] == 0
