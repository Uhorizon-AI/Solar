"""Rollout regressions: approved policy operations, real worker, deterministic provider.

Codex verification below is a test registry substitution only. Production continues
with capacity one, no enabled profiles, and Claude as the only verified adapter.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from supervisor_support import CORE_ROOT, PROFILE, wait_until
import solar_state
from review_inputs import batch

from rollout_policy import apply_policy as policy


@pytest.fixture(autouse=True)
def local_mcp_context(rig, monkeypatch):
    monkeypatch.chdir(rig.workspace)
    monkeypatch.setenv("SOLAR_ROOT", str(CORE_ROOT.parent))


ROUTER = r'''import json, os, pathlib, sys, time
payload = json.loads(sys.stdin.read())
folder = pathlib.Path(os.environ['PR4_PROVIDER_DIR'])
task = payload['request_id'].removeprefix('task_')
text = payload['text']
def emit(event):
    line = json.dumps(dict(event=event, task=task, t=time.time())) + '\n'
    fd = os.open(folder / 'events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try: os.write(fd, line.encode())
    finally: os.close(fd)
if payload.get('execution'):
    emit('start')
    (folder / ('started-' + task)).touch()
    count = int(os.environ['PR4_CHILD_COUNT'])
    deadline = time.monotonic() + 40
    while len(list(folder.glob('started-*'))) < count or not (folder / 'release').exists():
        if time.monotonic() > deadline:
            emit('barrier_timeout')
            raise SystemExit(1)
        time.sleep(0.02)
    time.sleep(0.08 + (sum(map(ord, task)) % 4) * 0.04)
    emit('end')
    reply = 'Review result for ' + task
elif '## Subtask results' in text:
    emit('synthesis')
    reply = '<delivery>One synthesis of all captured reviews.</delivery>'
else:
    emit('declaration')
    reply = '<subtasks>' + (folder / 'declarations.json').read_text() + '</subtasks>'
print(json.dumps(dict(status='success', reply_text=reply, provider_used=payload.get('provider'),
                     usage=dict(input_tokens=10, output_tokens=5))))
'''


def real_worker(rig, monkeypatch, count=3):
    """Copy the worker intact; replace only the provider/router entrypoint."""
    skills = rig.tmp / "worker-install" / "core" / "skills"
    for name in ("solar-async-tasks", "solar-state", "solar-paths", "solar-router"):
        shutil.copytree(CORE_ROOT / "skills" / name, skills / name,
                        ignore=shutil.ignore_patterns("__pycache__", ".venv", "*.pyc"))
    (skills / "solar-router/scripts/run_router.py").write_text(ROUTER)
    provider = rig.tmp / "provider"
    provider.mkdir()
    monkeypatch.setenv("PR4_PROVIDER_DIR", str(provider))
    monkeypatch.setenv("PR4_CHILD_COUNT", str(count))
    monkeypatch.setenv("SOLAR_ROOT", str(skills.parents[1]))
    source = rig.tmp / "evidence.txt"
    source.write_text("Known deterministic evidence.\n")
    fields, declarations, _ = batch(source, count)
    (provider / "declarations.json").write_text(json.dumps(declarations))
    with solar_state.session() as store:
        parent = store.task_create(fields, "Synthesize the approved captured reviews.", status="draft")
        store.task_approve(parent, actor="rollout-test")
    script = skills / "solar-async-tasks/scripts/execute_active.sh"
    return parent, provider, lambda task, token: ["bash", str(script), "--task", task, "--token", token]


def provider_events(folder):
    path = folder / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def children(parent):
    with solar_state.session() as store:
        raw = store.task_field(parent, "subtask_ids") or ""
    return [item.split("=", 1)[1] for item in raw.split(",") if item]


def test_approved_parent_three_derived_reviews_overlap_and_synthesize_once(rig, monkeypatch):
    policy(3)
    parent, provider, executor = real_worker(rig, monkeypatch)
    with rig.running(executor=executor, poll=0.1):
        wait_until(lambda: len([e for e in provider_events(provider) if e["event"] == "start"]) == 3,
                   60, what="three real workers at the provider barrier")
        ids = children(parent)
        with solar_state.session() as store:
            auth = list(store.conn.execute("SELECT task_id, parent_digest FROM task_authorizations"))
            assert {row["task_id"] for row in auth} == set(ids)
            assert all(row["parent_digest"] == store.task_field(parent, "approved_digest") for row in auth)
        (provider / "release").touch()
        wait_until(lambda: rig.status(parent) == "completed", 90, what="one synthesis")
    events = provider_events(provider)
    assert len([e for e in events if e["event"] == "synthesis"]) == 1
    starts = [e["t"] for e in events if e["event"] == "start"]
    ends = [e["t"] for e in events if e["event"] == "end"]
    assert len(starts) == len(ends) == 3 and max(starts) < min(ends)
    assert not [e for e in events if e["event"] == "barrier_timeout"]
    with solar_state.session() as store:
        assert store.conn.execute("SELECT count(*) FROM audit WHERE event='subtask_synthesis_started'").fetchone()[0] == 1
        assert all(store.task_status(task) == "completed" for task in ids)
        assert "One synthesis" in store.task_get(parent)["body"]


@pytest.mark.parametrize("capacity", [3, 5])
def test_applied_policy_reduction_keeps_running_results_and_blocks_new_admission(rig, capacity):
    policy(capacity)
    tasks = [rig.reader(f"Run {i}", provider="codex", spec=dict(gate="release", hold=0.1 + i * 0.04,
                 barrier=dict(name="all-started", parties=capacity))) for i in range(capacity)]
    pending = rig.reader("Zz next", provider="codex", spec=dict(hold=0.1))
    with rig.running(poll=0.1):
        wait_until(lambda: len(rig.events("start")) == capacity, 30)
        policy(1)
        assert all(rig.status(task) == "active" for task in tasks)
        assert rig.status(pending) == "queued"
        rig.gate("release")
        wait_until(lambda: all(rig.status(task) == "completed" for task in tasks + [pending]), 60)
    assert len(rig.events("completed")) == capacity + 1
    assert rig.max_overlap() == capacity
    assert max(rig.first("start", t) for t in tasks) < min(rig.first("end", t) for t in tasks)
    assert rig.first("start", pending) >= max(rig.first("end", t) for t in tasks)
    assert rig.first("start", pending) - max(rig.first("end", t) for t in tasks) <= 2.0
    assert rig.events("barrier_timeout") == []
    assert all(len(rig.events("start", task)) == 1 for task in tasks + [pending])


@pytest.mark.parametrize("enabled,undeclared", [(True, True), (False, False)])
def test_applied_capacity_five_preserves_exclusive_admission(rig, enabled, undeclared):
    policy(5, enabled=enabled)
    tasks = [rig.reader(f"Reader {i}", spec=dict(hold=0.12 + 0.05 * i)) for i in range(3)]
    if undeclared:
        exclusive = rig.legacy("Exclusive", spec=dict(hold=0.2))
        tasks.append(exclusive)
    with rig.running(poll=0.1):
        wait_until(lambda: all(rig.status(task) == "completed" for task in tasks), 60)
    starts = {task: rig.first("start", task) for task in tasks}
    ends = {task: rig.first("end", task) for task in tasks}
    if undeclared:
        assert all(ends[t] <= starts[exclusive] or starts[t] >= ends[exclusive]
                   for t in tasks if t != exclusive)
    else:
        assert rig.max_overlap() == 1
    assert all(len(rig.events("start", task)) == 1 for task in tasks)
