"""The completion notice is the one-screen delivery the executor wrote.

Covers the three hand-offs it depends on: create.sh carrying the declared scope
and the delivery flag into the task, the worker copying `<delivery>` into
`## Delivery` without touching the provider's own `## Result`, and the notifier
sending that section instead of a fixed line plus a path to a file on the Mac.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# core/tests/skills/solar-async-tasks/ → parents[3] = core/
CORE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = CORE_ROOT / "skills" / "solar-async-tasks" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import execute_active as ea  # noqa: E402


# ---------------------------------------------------------------------------
# create.sh: the declared scope reaches the task
# ---------------------------------------------------------------------------

def _create(tmp_path: Path, metadata: dict) -> Path:
    root = tmp_path / "runtime" / "async-tasks"
    root.mkdir(parents=True)
    body = tmp_path / "body.md"
    body.write_text("work\n", encoding="utf-8")
    env = {
        **os.environ,
        "SOLAR_WORKSPACE": str(tmp_path),
        "SOLAR_TASK_ROOT": str(root),
    }
    result = subprocess.run(
        [
            "bash", str(SCRIPTS / "create.sh"), "--queued",
            "--body-file", str(body),
            "--metadata", json.dumps(metadata),
            "Scoped task",
        ],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return next((root / "queued").glob("*.md"))


def test_create_writes_declared_scope_and_ignores_unknown_keys(tmp_path):
    task = _create(tmp_path, {
        "origin_channel": "telegram",
        "origin_chat_id": "456",
        "origin_request_id": "telegram:456:9",
        "object": "update docs/x.md\n  as agreed",
        "scope": "read planets/",
        "effect": "edit docs/x.md",
        "delivery_expected": True,
        "unexpected": "dropped",
    })
    text = task.read_text(encoding="utf-8")
    # Prose arrives wrapped and has to survive as one frontmatter line.
    assert 'object: "update docs/x.md as agreed"' in text
    assert 'scope: "read planets/"' in text
    assert 'effect: "edit docs/x.md"' in text
    assert "delivery_expected: true" in text
    assert "unexpected" not in text
    assert "notify_when: completed" in text


def test_create_fails_loudly_when_the_task_cannot_be_written(tmp_path):
    """A provider sandbox that cannot write the queue must not be told it worked."""
    root = tmp_path / "runtime" / "async-tasks"
    (root / "queued").mkdir(parents=True)
    (root / "queued").chmod(0o500)
    body = tmp_path / "body.md"
    body.write_text("work\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [
                "bash", str(SCRIPTS / "create.sh"), "--queued",
                "--body-file", str(body), "Unwritable task",
            ],
            env={**os.environ, "SOLAR_WORKSPACE": str(tmp_path),
                 "SOLAR_TASK_ROOT": str(root)},
            text=True, capture_output=True, timeout=30,
        )
    finally:
        (root / "queued").chmod(0o700)
    assert result.returncode != 0
    assert "Task created" not in result.stdout
    assert "was not written" in result.stderr


def test_create_leaves_no_task_when_the_write_dies_halfway(tmp_path):
    """Some bytes reaching disk is not the same as the task being written.

    A file size limit cuts the redirect after it has already emitted content,
    which is what a full disk or a killed sandbox looks like.
    """
    root = tmp_path / "runtime" / "async-tasks"
    (root / "queued").mkdir(parents=True)
    body = tmp_path / "body.md"
    body.write_text("x" * 20000 + "\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c",
         f'ulimit -f 1; exec bash {SCRIPTS / "create.sh"} --queued '
         f'--body-file {body} "Truncated task"'],
        env={**os.environ, "SOLAR_WORKSPACE": str(tmp_path),
             "SOLAR_TASK_ROOT": str(root)},
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode != 0
    assert "Task created" not in result.stdout
    assert "ID:" not in result.stdout
    # Neither the task nor the partial file it was being written into.
    assert list((root / "queued").iterdir()) == []


def test_create_without_scope_keeps_previous_shape(tmp_path):
    task = _create(tmp_path, {"origin_channel": "telegram", "origin_chat_id": "456"})
    text = task.read_text(encoding="utf-8")
    assert "object:" not in text
    assert "delivery_expected" not in text
    assert "notify_when: completed" in text


# ---------------------------------------------------------------------------
# execute_active: the worker copies the delivery, never the whole account
# ---------------------------------------------------------------------------

def _task(tmp_path: Path, extra: str = "", body: str = "# Task\n") -> Path:
    path = tmp_path / "task.md"
    path.write_text(
        '---\nid: "t1"\ntitle: "T"\nstatus: active\n' + extra + "---\n\n" + body,
        encoding="utf-8",
    )
    return path


def test_last_delivery_block_wins_and_result_is_untouched(tmp_path):
    task = _task(tmp_path, body="# Task\n\n## Result\n\nThe long account.\n")
    ea.record_delivery(task, (
        "Format example: <delivery>IGNORE ME</delivery>\n"
        "Here is the work.\n"
        "<delivery>\nRESULTADO: existe x.md\nEVIDENCIA: docs/x.md\n</delivery>"
    ))
    text = task.read_text(encoding="utf-8")
    assert "## Delivery\n\nRESULTADO: existe x.md\nEVIDENCIA: docs/x.md" in text
    assert "IGNORE ME" not in text
    assert "The long account." in text


def test_rerun_replaces_its_own_section(tmp_path):
    task = _task(tmp_path)
    ea.record_delivery(task, "<delivery>first</delivery>")
    ea.record_delivery(task, "<delivery>second</delivery>")
    text = task.read_text(encoding="utf-8")
    assert text.count("## Delivery") == 1
    assert "first" not in text
    assert "second" in text


def test_missing_delivery_is_marked_only_when_it_was_asked_for(tmp_path):
    asked = _task(tmp_path, extra="delivery_expected: true\n")
    ea.record_delivery(asked, "No block here.")
    assert "delivery_missing: true" in asked.read_text(encoding="utf-8")

    not_asked = tmp_path / "plain.md"
    not_asked.write_text('---\nid: "t2"\nstatus: active\n---\n\n# Task\n', encoding="utf-8")
    ea.record_delivery(not_asked, "No block here.")
    assert "delivery_missing" not in not_asked.read_text(encoding="utf-8")


def test_rerun_without_a_block_does_not_notify_the_previous_delivery(tmp_path):
    """A parent runs twice by design, and can be requeued from error."""
    task = _task(tmp_path, extra="delivery_expected: true\n")
    ea.record_delivery(task, "<delivery>stale delivery from run one</delivery>")
    ea.record_delivery(task, "Run two produced no block.")
    text = task.read_text(encoding="utf-8")
    assert "stale delivery from run one" not in text
    assert "## Delivery" not in text
    assert "delivery_missing: true" in text


def test_flags_describe_the_current_run_not_an_earlier_one(tmp_path):
    task = _task(tmp_path, extra="delivery_expected: true\n")
    long_delivery = ("x" * (ea.DELIVERY_MAX_CHARS + 200)) + "\nEVIDENCIA: /log"
    ea.record_delivery(task, f"<delivery>\n{long_delivery}\n</delivery>")
    assert "delivery_truncated: true" in task.read_text(encoding="utf-8")

    ea.record_delivery(task, "<delivery>short one</delivery>")
    text = task.read_text(encoding="utf-8")
    assert "delivery_truncated" not in text
    assert "delivery_missing" not in text
    assert "short one" in text


def test_oversized_delivery_is_cut_but_keeps_its_evidence_line(tmp_path):
    evidence = "EVIDENCIA: /path/to/log"
    long_delivery = ("x" * (ea.DELIVERY_MAX_CHARS + 500)) + "\n" + evidence
    task = _task(tmp_path, extra="delivery_expected: true\n")
    ea.record_delivery(task, f"<delivery>\n{long_delivery}\n</delivery>")
    text = task.read_text(encoding="utf-8")
    assert "delivery_truncated: true" in text
    assert text.rstrip().endswith(evidence)
    section = text.split("## Delivery\n\n", 1)[1].rstrip()
    assert len(section) <= ea.DELIVERY_MAX_CHARS


# ---------------------------------------------------------------------------
# notify_if_configured.sh: the delivery is the message
# ---------------------------------------------------------------------------

def _notify_env(tmp_path: Path):
    workspace = tmp_path / "workspace"
    install = tmp_path / "install"
    root = workspace / "runtime/async-tasks"
    (root / "completed").mkdir(parents=True)
    sender = install / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.parent.mkdir(parents=True)
    sender.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n'
    )
    sender.chmod(0o755)
    env = {
        **os.environ,
        "SOLAR_WORKSPACE": str(workspace),
        "SOLAR_ROOT": str(install),
        "SOLAR_TASK_ROOT": str(root),
        "TELEGRAM_CHAT_ID": "456",
        "TELEGRAM_ALLOWED_CHAT_IDS": "456",
        "TELEGRAM_BOT_TOKEN": "fake",
    }
    return workspace, root, env


def _completed(root: Path, extra: str, body: str) -> Path:
    path = root / "completed" / "task.md"
    path.write_text(
        '---\nid: "t1"\ntitle: "Some_task"\nstatus: completed\n'
        'notify_when: completed\norigin_chat_id: "456"\n' + extra + "---\n\n" + body,
        encoding="utf-8",
    )
    return path


def _notify(task: Path, env) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPTS / "notify_if_configured.sh"), str(task)],
        env=env, text=True, capture_output=True, timeout=30,
    )


def test_notice_is_the_delivery_with_its_evidence_last(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _completed(
        root,
        'result_path: "/local/path.log"\ndelivery_expected: true\n',
        "# T\n\n## Result\n\nThe long account.\n\n"
        "## Delivery\n\nRESULTADO: existe x.md\nEVIDENCIA: docs/x.md\n",
    )
    assert _notify(task, env).returncode == 0
    sent = (workspace / "sent.log").read_text(encoding="utf-8")
    assert sent.startswith("RESULTADO: existe x.md")
    assert sent.rstrip().endswith("EVIDENCIA: docs/x.md")
    assert "Task completed" not in sent
    assert "The long account." not in sent
    assert "/local/path.log" not in sent


def test_expected_delivery_that_never_came_says_so(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _completed(
        root,
        'result_path: "/local/path.log"\ndelivery_expected: true\n',
        "# T\n\n## Result\n\nThe long account.\n",
    )
    assert _notify(task, env).returncode == 0
    sent = (workspace / "sent.log").read_text(encoding="utf-8")
    assert "Task finished without a delivery" in sent
    assert "/local/path.log" in sent
    assert "The long account." not in sent


def test_task_that_never_asked_for_a_delivery_keeps_the_old_notice(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _completed(root, 'result_path: "/local/path.log"\n', "# T\n")
    assert _notify(task, env).returncode == 0
    sent = (workspace / "sent.log").read_text(encoding="utf-8")
    assert sent.startswith("Task completed: Some_task")
    assert "/local/path.log" in sent
