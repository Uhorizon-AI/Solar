"""activate.sh, approve.sh and start_next.sh honour the approval the claim checks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "solar-async-tasks" / "scripts"
STATE = Path(__file__).resolve().parents[3] / "skills" / "solar-state" / "scripts"
sys.path.insert(0, str(STATE))

import solar_state  # noqa: E402

from queue_mirror import env_for  # noqa: E402
from reservation_tokens import token_of


def _env(tmp_path: Path) -> dict:
    return env_for(tmp_path / "runtime" / "async-tasks", {**os.environ, "SOLAR_WORKSPACE": str(tmp_path)})


def _script(env: dict, name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPTS / name), *args], env=env, text=True,
                          capture_output=True, timeout=60)


def _task(title: str, status: str = "draft", **extra) -> str:
    fields = {"title": json.dumps(title), "priority": "normal",
              "scheduled_time": json.dumps("now"), "recurring": "false", **extra}
    with solar_state.session() as store:
        task_id = store.task_create(list(fields.items()), f"\n# {title}\n\nDo it.\n", status="draft")
        if status == "queued":
            store.task_approve(task_id)
        return task_id


def _values(task_id: str) -> dict:
    with solar_state.session() as store:
        return {k: solar_state.value_of(v) for k, v in store.task_get(task_id)["frontmatter"]}


def _tamper(task_id: str) -> None:
    with solar_state.session() as store:
        store.task_set_body(task_id, store.task_get(task_id)["body"] + "\nAlso do something else.\n")


def test_approve_sh_leaves_a_digest_the_claim_accepts(tmp_path):
    env = _env(tmp_path)
    task_id = _task("From the script")
    done = _script(env, "approve.sh", task_id)
    assert done.returncode == 0, done.stderr
    values = _values(task_id)
    assert values["approved_digest"].startswith("v2:") and values["approved_definition"] == "Do it."
    started = _script(env, "start_next.sh")
    assert started.returncode == 0 and f"[{task_id}]" in started.stdout
    refused = _script(env, "approve.sh", task_id)
    assert refused.returncode != 0 and "approved and queued" not in refused.stdout


def test_activate_sh_approves_claims_and_stamps_a_recurring_run(tmp_path):
    env = _env(tmp_path)
    task_id = _task("Recurring", recurring="true", recurring_min_interval="3600")
    done = _script(env, "activate.sh", task_id)
    assert done.returncode == 0 and "Activated" in done.stdout, done.stderr
    values = _values(task_id)
    assert values["status"] == "active" and values["approved_digest"].startswith("v2:")
    assert values["recurring_last_run"]


def test_activate_fails_when_claim_rejected(tmp_path):
    env = _env(tmp_path)
    task_id = _task("Waits", "queued", blocked_by_task_ids='"nobody"')
    _tamper(task_id)
    before = _values(task_id)
    done = _script(env, "activate.sh", task_id)
    assert done.returncode != 0
    assert "Activated" not in done.stdout
    assert "approval_digest_mismatch" in done.stderr and "reason=mismatch" in done.stderr
    after = _values(task_id)
    assert after["status"] == "queued"
    assert after["blocked_by_task_ids"] == before["blocked_by_task_ids"]   # not released
    with solar_state.session() as store:
        assert store.audit_rows("approval_digest_mismatch")[-1]["task_id"] == task_id


def test_activate_fails_when_the_task_was_taken_meanwhile(tmp_path):
    env = _env(tmp_path)
    task_id = _task("Taken", "queued")
    with solar_state.session() as store:
        assert store.task_claim(task_id, "someone-else")
    done = _script(env, "activate.sh", task_id)
    assert done.returncode == 0 and "already active" in done.stdout    # the existing, explicit case
    with solar_state.session() as store:
        store.task_release(task_id, "someone-else", token=token_of(store, task_id))
        store.task_set(task_id, "approved_digest", '"' + "0" * 64 + '"')
    done = _script(env, "activate.sh", task_id)
    assert done.returncode != 0 and "reason=legacy" in done.stderr


def test_rejected_claim_does_not_stamp_last_run(tmp_path):
    env = _env(tmp_path)
    task_id = _task("Recurring", "queued", recurring="true", recurring_min_interval="3600")
    _tamper(task_id)
    assert _script(env, "activate.sh", task_id).returncode != 0
    started = _script(env, "start_next.sh")
    assert started.returncode == 0 and "No tasks ready" in started.stdout
    assert "approval_digest_mismatch" in started.stderr
    values = _values(task_id)
    assert values["status"] == "queued" and "recurring_last_run" not in values


def test_start_next_skips_a_mismatching_task_and_starts_the_next(tmp_path):
    env = _env(tmp_path)
    first = _task("First", "queued", priority='"high"')
    second = _task("Second", "queued")
    _tamper(first)
    started = _script(env, "start_next.sh")
    assert started.returncode == 0 and f"[{second}]" in started.stdout, started.stderr
    assert _values(first)["status"] == "queued"
