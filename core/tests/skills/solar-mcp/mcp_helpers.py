"""Shared helpers for the solar-mcp tests: call the three public tools."""
from __future__ import annotations

import json

import mcp_approve
import mcp_server


def payload(answer: dict) -> dict:
    """The JSON a wire answer carries."""
    return json.loads(answer["result"]["content"][0]["text"])


def call(tool: str, arguments: dict) -> tuple[dict, bool]:
    return mcp_server.call_tool(tool, arguments)


def search(**arguments) -> dict:
    body, error = call("solar_search", arguments)
    assert not error, body
    return body["result"]


def docs(**arguments) -> dict:
    body, error = call("solar_docs", arguments)
    assert not error, body
    return body["result"]


def execute(operation: str, arguments: dict, *, approved: bool = True) -> tuple[dict, bool]:
    """Run an operation; with `approved`, through an exact-call approval like the client flow."""
    request = dict(operation=operation, arguments=arguments)
    if approved:
        request["approval_id"] = mcp_approve.grant(operation, arguments, 900, "test")["approval_id"]
    return call("solar_execute", request)


def run(operation: str, arguments: dict) -> dict:
    """Approved success path: returns the operation result."""
    body, error = execute(operation, arguments)
    assert not error, body
    return body["result"]


def new_task(title: str = "Draft", instructions: str = "Do the work.", **extra) -> dict:
    return run("task.create", dict(title=title, instructions=instructions, **extra))


def stored(task_id: str) -> dict:
    import solar_state
    with solar_state.session() as store:
        return store.task_get(task_id)


def queue_and_authorize(task_id: str, expected_row_version: int) -> dict:
    """Approve through the operation, then authorize the run: what a task that is not confined to a
    verified read-only profile needs before a worker may claim it."""
    queued = run("task.approve", dict(task_id=task_id, expected_row_version=expected_row_version))
    run("task.authorize_run", dict(task_id=task_id, expected_row_version=queued["row_version"]))
    return queued
