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
from queue_mirror import env_for, mirror, seed, task_id_of  # noqa: E402


# ---------------------------------------------------------------------------
# create.sh: the declared scope reaches the task
# ---------------------------------------------------------------------------

def _create(tmp_path: Path, metadata: dict) -> Path:
    root = tmp_path / "runtime" / "async-tasks"
    body = tmp_path / "body.md"
    body.write_text("work\n", encoding="utf-8")
    env = env_for(root, {**os.environ, "SOLAR_WORKSPACE": str(tmp_path)})
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
    mirror(root)
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


def test_create_refuses_when_the_runtime_is_not_sqlite(tmp_path):
    """A runtime that is still files must not be told a task was created."""
    root = tmp_path / "runtime" / "async-tasks"
    root.mkdir(parents=True)
    body = tmp_path / "body.md"
    body.write_text("work\n", encoding="utf-8")
    env = {**os.environ, "SOLAR_WORKSPACE": str(tmp_path), "SOLAR_TASK_ROOT": str(root)}
    env["SOLAR_RUNTIME_ROOT"] = str(tmp_path / "runtime")
    env.pop("SOLAR_APP_DATA", None)
    result = subprocess.run(
        ["bash", str(SCRIPTS / "create.sh"), "--queued", "--body-file", str(body), "Unwritten"],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode != 0
    assert "Task created" not in result.stdout
    assert "ID:" not in result.stdout
    assert list(root.rglob("*.md")) == []


def test_create_without_scope_keeps_previous_shape(tmp_path):
    task = _create(tmp_path, {"origin_channel": "telegram", "origin_chat_id": "456"})
    text = task.read_text(encoding="utf-8")
    assert "object:" not in text
    assert "delivery_expected" not in text
    assert "notify_when: completed" in text


# ---------------------------------------------------------------------------
# execute_active: the worker copies the delivery, never the whole account
# ---------------------------------------------------------------------------

def _task(tmp_path: Path, extra: str = "", body: str = "# Task\n", task_id: str = "t1") -> Path:
    root = tmp_path / "async-tasks"
    folder = root / "active"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{task_id}.md"
    path.write_text(
        f'---\nid: "{task_id}"\ntitle: "T"\nstatus: active\n' + extra + "---\n\n" + body,
        encoding="utf-8",
    )
    seed(root)
    return path


def record(task: Path, reply: str) -> str:
    ea.record_delivery(task_id_of(task), reply)
    mirror(task.parent.parent)
    return task.read_text(encoding="utf-8")


def test_last_delivery_block_wins_and_result_is_untouched(tmp_path):
    task = _task(tmp_path, body="# Task\n\n## Result\n\nThe long account.\n")
    text = record(task, (
        "Format example: <delivery>IGNORE ME</delivery>\n"
        "Here is the work.\n"
        "<delivery>\nRESULTADO: existe x.md\nEVIDENCIA: docs/x.md\n</delivery>"
    ))
    assert "## Delivery\n\nRESULTADO: existe x.md\nEVIDENCIA: docs/x.md" in text
    assert "IGNORE ME" not in text
    assert "The long account." in text


def test_rerun_replaces_its_own_section(tmp_path):
    task = _task(tmp_path)
    record(task, "<delivery>first</delivery>")
    text = record(task, "<delivery>second</delivery>")
    assert text.count("## Delivery") == 1
    assert "first" not in text
    assert "second" in text


def test_missing_delivery_is_marked_only_when_it_was_asked_for(tmp_path):
    asked = _task(tmp_path, extra="delivery_expected: true\n")
    assert "delivery_missing: true" in record(asked, "No block here.")

    not_asked = _task(tmp_path, task_id="t2")
    assert "delivery_missing" not in record(not_asked, "No block here.")


def test_rerun_without_a_block_does_not_notify_the_previous_delivery(tmp_path):
    """A parent runs twice by design, and can be requeued from error."""
    task = _task(tmp_path, extra="delivery_expected: true\n")
    record(task, "<delivery>stale delivery from run one</delivery>")
    text = record(task, "Run two produced no block.")
    assert "stale delivery from run one" not in text
    assert "## Delivery" not in text
    assert "delivery_missing: true" in text


def test_flags_describe_the_current_run_not_an_earlier_one(tmp_path):
    task = _task(tmp_path, extra="delivery_expected: true\n")
    long_delivery = ("x" * (ea.DELIVERY_MAX_CHARS + 200)) + "\nEVIDENCIA: /log"
    assert "delivery_truncated: true" in record(task, f"<delivery>\n{long_delivery}\n</delivery>")

    text = record(task, "<delivery>short one</delivery>")
    assert "delivery_truncated" not in text
    assert "delivery_missing" not in text
    assert "short one" in text


def test_oversized_delivery_is_cut_but_keeps_its_evidence_line(tmp_path):
    evidence = "EVIDENCIA: /path/to/log"
    long_delivery = ("x" * (ea.DELIVERY_MAX_CHARS + 500)) + "\n" + evidence
    task = _task(tmp_path, extra="delivery_expected: true\n")
    text = record(task, f"<delivery>\n{long_delivery}\n</delivery>")
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
    root = task.parent.parent
    merged = env_for(root, env)
    seed(root)
    return subprocess.run(
        ["bash", str(SCRIPTS / "notify_if_configured.sh"), task_id_of(task)],
        env=merged, text=True, capture_output=True, timeout=30,
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


# ---------------------------------------------------------------------------
# notify_when: delivery (opt-in, quiet)
# ---------------------------------------------------------------------------

def _task_with(root: Path, status: str, notify_when: str, body: str, extra: str = "", recorded: bool = True) -> Path:
    extra = ("delivery_recorded: true\n" if recorded else "") + extra
    folder = root / status
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "task.md"
    path.write_text(
        f'---\nid: "t1"\ntitle: "Some_task"\nstatus: {status}\n'
        f'notify_when: {notify_when}\norigin_chat_id: "456"\n' + extra + "---\n\n" + body,
        encoding="utf-8",
    )
    return path


def _sent(workspace: Path) -> str:
    log = workspace / "sent.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_delivery_option_sends_the_delivery_once(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _task_with(root, "completed", "delivery,failed",
                      "# T\n\n## Delivery\n\nDECISION: nueva\nEVIDENCIA: x\n")
    assert _notify(task, env).returncode == 0
    assert _notify(task, env).returncode == 0          # the per-run record keeps a second call silent
    sent = _sent(workspace)
    assert sent.count("DECISION: nueva") == 1 and "Task completed" not in sent


def test_delivery_option_is_silent_without_a_delivery_even_after_a_delivering_run(tmp_path):
    # The worker side: run two has no block, so the section run one wrote is gone.
    run_dir = tmp_path / "run"
    task = _task(run_dir, extra="delivery_expected: true\n")
    record(task, "<delivery>run one decision</delivery>")
    text = record(task, "Run two: nothing new.")
    assert "## Delivery" not in text and "run one decision" not in text
    # The notifier side, on that very body, then on a block that is present but empty.
    for name, body in (("absent", text.split("---\n\n", 1)[1]), ("empty", "# T\n\n## Delivery\n\n")):
        workspace, root, env = _notify_env(tmp_path / name)
        done = _task_with(root, "completed", "delivery,failed", body)
        assert _notify(done, env).returncode == 0
        assert _sent(workspace) == ""


def test_delivery_option_with_failed_announces_a_failure(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _task_with(root, "error", "delivery,failed", "# T\n", 'failure_code: "provider_timeout"\n')
    assert _notify(task, env).returncode == 0
    sent = _sent(workspace)
    assert sent.count("Task failed and needs attention: Some_task") == 1
    assert "Reason: provider_timeout" in sent


def test_delivery_alone_keeps_a_failure_silent(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _task_with(root, "error", "delivery", "# T\n")
    assert _notify(task, env).returncode == 0
    assert _sent(workspace) == ""


def test_existing_notify_values_keep_their_notices(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    done = _task_with(root, "completed", "completed", "# T\n")      # no delivery: the old brief line
    assert _notify(done, env).returncode == 0
    assert _sent(workspace).startswith("Task completed: Some_task")
    workspace, root, env = _notify_env(tmp_path / "failure")
    failed = _task_with(root, "error", "completed", "# T\n")        # bare completed still reports failures
    assert _notify(failed, env).returncode == 0
    assert "Task failed and needs attention" in _sent(workspace)


def test_delivery_alone_announces_a_success_with_text(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _task_with(root, "completed", "delivery", "# T\n\n## Delivery\n\nDECISION: nueva\nEVIDENCIA: x\n")
    assert _notify(task, env).returncode == 0
    assert _sent(workspace).startswith("DECISION: nueva")


def test_delivery_is_not_sent_twice_for_the_same_run(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _task_with(root, "completed", "delivery", "# T\n\n## Delivery\n\nDECISION: nueva\n",
                      'notify_run: "r1"\nnotify_delivered: true\nnotify_delivered_run: "r1"\n')
    assert _notify(task, env).returncode == 0
    assert _sent(workspace) == ""


def test_expected_delivery_that_never_came_is_silent_with_the_delivery_option(tmp_path):
    for name, when in (("alone", "delivery"), ("with_failed", "delivery,failed")):
        workspace, root, env = _notify_env(tmp_path / name)
        task = _task_with(root, "completed", when, "# T\n\n## Result\n\nAccount.\n",
                          "delivery_expected: true\ndelivery_missing: true\n")
        assert _notify(task, env).returncode == 0
        assert "Task finished without a delivery" not in _sent(workspace)
        assert _sent(workspace) == ""


def test_a_delivery_with_headings_is_sent_whole(tmp_path):
    workspace, root, env = _notify_env(tmp_path)
    task = _task_with(root, "completed", "delivery",
                      "# T\n\n## Result\n\nAccount.\n\n## Delivery\n\n## Resumen\nAsunto uno\n\n## Decision\nAprobar\n")
    assert _notify(task, env).returncode == 0
    sent = _sent(workspace)
    assert sent.startswith("## Resumen") and "Asunto uno" in sent and "## Decision\nAprobar" in sent
    assert "Account." not in sent


def test_a_rerun_replaces_a_delivery_that_holds_headings(tmp_path):
    task = _task(tmp_path, extra="delivery_expected: true\n")
    record(task, "<delivery>\n## Resumen\nold text\n## Decision\nold ask\n</delivery>")
    text = record(task, "<delivery>\n## Resumen\nnew text\n</delivery>")
    assert text.count("## Delivery") == 1
    assert "old text" not in text and "old ask" not in text and "new text" in text


def test_a_new_delivery_keeps_the_sections_the_runtime_wrote_after_it(tmp_path):
    body = ("# T\n\n## Delivery\n\n## Resumen\nold text\n\n"
            "## Subtask results\n\n### a — completed\n\nCHILD TEXT\n")
    task = _task(tmp_path, body=body)
    text = record(task, "<delivery>\n## Resumen\nnew text\n</delivery>")
    assert "CHILD TEXT" in text and "old text" not in text and "new text" in text
    assert text.count("## Delivery") == 1


def test_the_notice_stops_at_a_runtime_heading_and_keeps_inner_ones(tmp_path):
    for name, heading in (("subtasks", "## Subtask results"), ("error", "## Execution Error"), ("result", "## Result")):
        workspace, root, env = _notify_env(tmp_path / name)
        task = _task_with(root, "completed", "delivery",
                          f"# T\n\n## Delivery\n\n## Resumen\nAsunto\n\n## Decision\nAprobar\n\n{heading}\n\nFOREIGN TEXT\n")
        assert _notify(task, env).returncode == 0
        sent = _sent(workspace)
        assert "## Resumen" in sent and "## Decision\nAprobar" in sent
        assert "FOREIGN TEXT" not in sent


def test_the_two_delivery_cuts_use_the_same_headings():
    import re
    import solar_state
    script = (SCRIPTS / "notify_if_configured.sh").read_text(encoding="utf-8")
    in_awk = re.search(r"found && /\^## \(([^)]*)\)", script).group(1).split("|")
    expected = [h[3:] for h in solar_state.RUNTIME_SECTIONS if h != "## Delivery"]
    assert sorted(in_awk) == sorted(expected)


def test_a_delivery_heading_that_the_executor_did_not_record_sends_nothing(tmp_path):
    for name, heading in (("exact", "## Delivery"), ("trailing_space", "## Delivery ")):
        workspace, root, env = _notify_env(tmp_path / name)
        task = _task_with(root, "completed", "delivery",
                          f"# T\n\nInstructions.\n\n{heading}\n\nSECRET INSTRUCTIONS\n", recorded=False)
        assert _notify(task, env).returncode == 0
        assert _sent(workspace) == ""


def test_the_worker_marks_only_a_delivery_it_recorded(tmp_path):
    task = _task(tmp_path / "a")
    assert "delivery_recorded: true" in record(task, "<delivery>x</delivery>")
    assert "delivery_recorded" not in record(task, "No block this time.")


def test_a_delivery_that_holds_a_runtime_heading_is_kept_whole_and_the_next_section_is_not_sent(tmp_path):
    task = _task(tmp_path / "w", body="# T\n")
    text = record(task, "<delivery>\n## Result\nAsunto uno\n## Subtask results\nAsunto dos\n</delivery>")
    assert text.count("\n## Result") == 0 and " ## Result\nAsunto uno" in text
    workspace, root, env = _notify_env(tmp_path / "n")
    body = text.split("---\n\n", 1)[1] + "\n## Result\n\nFOREIGN TEXT\n"
    done = _task_with(root, "completed", "delivery", body)
    assert _notify(done, env).returncode == 0
    sent = _sent(workspace)
    assert "Asunto uno" in sent and "Asunto dos" in sent and "FOREIGN TEXT" not in sent


_LOOKALIKE = "# T\n\nInstructions.\n\n## Delivery \n\nSECRET INSTRUCTIONS\n\n## Límites\n\nKEEP THIS\n"


def test_a_lookalike_heading_in_the_instructions_survives_an_attempt_without_a_block(tmp_path):
    task = _task(tmp_path / "w", body=_LOOKALIKE)
    text = record(task, "No block this time.")
    assert "## Delivery \n\nSECRET INSTRUCTIONS\n\n## Límites\n\nKEEP THIS" in text
    assert "delivery_recorded" not in text
    workspace, root, env = _notify_env(tmp_path / "n")
    done = _task_with(root, "completed", "delivery", text.split("---\n\n", 1)[1], recorded=False)
    assert _notify(done, env).returncode == 0
    assert _sent(workspace) == ""


def test_a_real_delivery_is_sent_instead_of_a_lookalike_in_the_instructions(tmp_path):
    task = _task(tmp_path / "w", body=_LOOKALIKE)
    text = record(task, "<delivery>REAL DELIVERY</delivery>")
    assert "KEEP THIS" in text and "SECRET INSTRUCTIONS" in text
    workspace, root, env = _notify_env(tmp_path / "n")
    done = _task_with(root, "completed", "delivery", text.split("---\n\n", 1)[1])
    assert _notify(done, env).returncode == 0
    sent = _sent(workspace)
    assert sent.strip() == "REAL DELIVERY"


def test_a_delivery_with_crlf_endings_and_a_leading_runtime_heading_is_sent_whole(tmp_path):
    task = _task(tmp_path / "w", body="# T\n")
    text = record(task, "<delivery>\r\n## Result\r\nAsunto uno\r\n</delivery>")
    assert "\r" not in text and " ## Result\nAsunto uno" in text
    workspace, root, env = _notify_env(tmp_path / "n")
    done = _task_with(root, "completed", "delivery", text.split("---\n\n", 1)[1] + "\n## Result\n\nFOREIGN\n")
    assert _notify(done, env).returncode == 0
    sent = _sent(workspace)
    assert "Asunto uno" in sent and "FOREIGN" not in sent
