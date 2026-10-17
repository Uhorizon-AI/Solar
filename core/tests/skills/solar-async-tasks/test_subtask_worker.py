"""The provider declares subtasks; the worker creates them.

The provider runs sandboxed and cannot write into the task queue, so everything
here checks the path that does not depend on it: a <subtasks> block becomes real
children, the parent remembers which ones were its own, and their results come
back to it without any child ever touching the queue.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from queue_mirror import env_for, mirror, seed, task_id_of
from reservation_tokens import token_of

SCRIPTS = Path(__file__).resolve().parents[3] / "skills/solar-async-tasks/scripts"
EXECUTE = SCRIPTS / "execute_active.py"

ROUTER_STUB = """#!/usr/bin/env python3
import json, os, pathlib, sys
sys.stdin.read()
marker = os.environ.get("STUB_MARKER")
if marker:
    pathlib.Path(marker).write_text("called", encoding="utf-8")
print(json.dumps({
    "status": "success",
    "reply_text": os.environ.get("STUB_REPLY", "done"),
    "provider_used": "codex",
    "usage": {"input_tokens": 12, "output_tokens": 4},
}))
"""


def make_root(tmp_path):
    root = tmp_path / "async-tasks"
    for name in ("active", "queued", "completed", "error", "logs", "archive", "cancelled",
                 "drafts", "planned"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def write_parent(root, extra=""):
    task = root / "active" / "parent.md"
    task.write_text(
        '---\nid: "parent-0001-aaaa"\ntitle: "Parent"\nstatus: active\npriority: normal\n'
        'object: "el informe"\nscope: "solo lectura"\neffect: "un resumen"\n'
        'origin_channel: "telegram"\norigin_chat_id: "456"\nnotify_when: completed\n'
        'delivery_expected: true\n' + extra + '---\n\n# Parent\n\nHaz el trabajo.\n',
        encoding="utf-8",
    )
    return task


def run_executor(task, root, reply, tmp_path, marker=None):
    router = tmp_path / "router_stub.py"
    router.write_text(ROUTER_STUB, encoding="utf-8")
    seed(root)
    env = env_for(root, {**os.environ, "STUB_REPLY": reply})
    if marker:
        env["STUB_MARKER"] = str(marker)
    else:
        env.pop("STUB_MARKER", None)
    proc = subprocess.run(
        [sys.executable, str(EXECUTE), task_id_of(task), str(router)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    mirror(root)
    return proc


def block(children):
    return "He repartido el trabajo.\n\n<subtasks>\n" + json.dumps(children) + "\n</subtasks>\n"


def manifest(task):
    for line in task.read_text(encoding="utf-8").splitlines():
        if line.startswith("subtask_ids:"):
            return [p for p in line.split(":", 1)[1].strip().strip('"').split(",") if p]
    return []


def children_files(root):
    return sorted((root / "queued").glob("*.md"))


# --- declaration → creation ------------------------------------------------


def test_rejected_batch_leaves_no_child_manifest(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    proc = run_executor(task, root, block([{"title": "Uno", "body": "Revisa A"}]), tmp_path)
    assert proc.returncode == 1
    rejected = root / "error" / "parent.md"
    assert "subtask_ids:" not in rejected.read_text()
    assert not children_files(root)


@pytest.mark.parametrize("reply,reason", [
    (block([{"title": f"Hijo {i}", "body": "x"} for i in range(6)]), "cap is 5"),
    (block([{"title": "Uno", "body": "x", "priority": "high"}]), "not allowed"),
    (block([{"title": "Uno", "body": "x", "provider": "gpt"}]), "unknown provider"),
    (block([{"title": "", "body": "x"}]), "no title"),
    (block([{"title": "Uno"}]), "no body"),
    (block([{"title": "U" * 121, "body": "x"}]), "over 120"),
    (block([{"title": "Uno", "body": "x" * 8001}]), "over 8000"),
    (block([]), "no children"),
    ("<subtasks>\nno soy json\n</subtasks>", "not valid JSON"),
    ('<subtasks>\n{"title": "Uno"}\n</subtasks>', "must be a JSON list"),
])
def test_a_bad_block_creates_nothing_and_names_the_reason(tmp_path, reply, reason):
    root = make_root(tmp_path)
    task = write_parent(root)
    proc = run_executor(task, root, reply, tmp_path)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not children_files(root)
    failed = root / "error" / "parent.md"
    assert failed.exists()
    text = failed.read_text(encoding="utf-8")
    assert "subtasks_rejected" in text
    assert reason in text


# --- depth is one, and one batch per request -------------------------------

def test_a_child_cannot_declare_grandchildren(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root, extra='parent_task_id: "some-parent"\n')
    proc = run_executor(task, root, block([{"title": "Nieto", "body": "no"}]), tmp_path)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not children_files(root)
    assert "subtask_ids" not in (root / "error/parent.md").read_text(encoding="utf-8")


def test_a_second_declaration_does_not_create_a_second_batch(tmp_path):
    root = make_root(tmp_path)
    child = root / "completed" / "child.md"
    child.write_text(
        '---\nid: "child-1"\ntitle: "Uno"\nstatus: completed\nsubtask_key: "k1"\n---\n\n# Uno\n',
        encoding="utf-8",
    )
    (root / "logs" / "child.log").write_text(
        "# Async Task Execution\n\n- outcome: success\n\n## Result\n\nlo hice\n", encoding="utf-8"
    )
    task = write_parent(root, extra='subtask_ids: "k1=child-1"\n')
    proc = run_executor(task, root, block([{"title": "Otro", "body": "no"}]), tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not children_files(root)
    assert manifest(task) == ["k1=child-1"]


# --- recovery: a crash mid-creation resumes -------------------------------


# --- results come back through the worker ---------------------------------

def _finished_child(root, folder, name, task_id, key, status, log_body):
    path = root / folder / f"{name}.md"
    extra = f'result_path: "{root / "logs" / (name + ".log")}"\n'
    path.write_text(
        f'---\nid: "{task_id}"\ntitle: "{name}"\nstatus: {status}\n'
        f'subtask_key: "{key}"\nparent_task_id: "parent-0001-aaaa"\n{extra}---\n\n# {name}\n',
        encoding="utf-8",
    )
    (root / "logs" / f"{name}.log").write_text(log_body, encoding="utf-8")
    return path


def test_the_worker_serves_the_results_including_the_child_that_failed(tmp_path):
    root = make_root(tmp_path)
    _finished_child(root, "completed", "uno", "child-1", "k1", "completed",
                    "# Async Task Execution\n\n- outcome: success\n\n## Result\n\nrevisé A\n")
    _finished_child(root, "error", "dos", "child-2", "k2", "error",
                    "# Async Task Execution\n\n- outcome: error\n\n## Error\n\n"
                    "- error_code: router_timeout\n- error: se agotó el tiempo\n")
    task = write_parent(root, extra='subtask_ids: "k1=child-1,k2=child-2"\n')

    proc = run_executor(task, root, "<delivery>listo</delivery>", tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    text = task.read_text(encoding="utf-8")
    assert "## Subtask results" in text
    assert "### k1 — completed" in text and "revisé A" in text
    assert "### k2 — error" in text and "router_timeout" in text
    # A failed child does not stop the parent from delivering.
    assert "## Delivery" in text and "listo" in text


def test_a_long_result_is_truncated_with_a_mark(tmp_path):
    root = make_root(tmp_path)
    _finished_child(root, "completed", "uno", "child-1", "k1", "completed",
                    "# Async Task Execution\n\n## Result\n\n" + ("x" * 5000))
    task = write_parent(root, extra='subtask_ids: "k1=child-1"\n')

    assert run_executor(task, root, "done", tmp_path).returncode == 0
    text = task.read_text(encoding="utf-8")
    assert "[truncated at 4000 characters]" in text
    assert "x" * 4001 not in text


def test_a_missing_child_is_reported_not_hidden(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root, extra='subtask_ids: "k1=child-gone"\n')
    assert run_executor(task, root, "done", tmp_path).returncode == 0
    assert "### k1 — missing" in task.read_text(encoding="utf-8")


def test_a_task_without_a_block_still_finishes_as_before(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    proc = run_executor(task, root, "todo hecho <delivery>ya está</delivery>", tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not children_files(root)
    text = task.read_text(encoding="utf-8")
    assert "subtask_ids" not in text
    assert "## Delivery" in text and "ya está" in text


# --- the shell side of the contract ---------------------------------------

def _ensure_framework(skills):
    """The copied scripts resolve solar-state next to themselves."""
    base = SCRIPTS.parent.parent
    for name in ("solar-state", "solar-paths"):
        dest = skills / name
        if not dest.exists():
            shutil.copytree(
                base / name, dest,
                ignore=shutil.ignore_patterns("__pycache__", ".venv", "*.pyc"),
            )


def run_bash(script, root, extra=None, args=("--once",), timeout=120):
    env = env_for(root, {**os.environ, **(extra or {})})
    seed(root)
    proc = subprocess.run(
        ["bash", str(script), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    mirror(root)
    return proc


def _worker_tree(tmp_path, executor_body):
    """A copy of the scripts with a stub executor, to test the wrapper itself."""
    skills = tmp_path / "skills"
    shutil.copytree(SCRIPTS, skills / "solar-async-tasks" / "scripts")
    _ensure_framework(skills)
    router = skills / "solar-router" / "scripts"
    router.mkdir(parents=True)
    (router / "run_router.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    stub = skills / "solar-async-tasks" / "scripts" / "execute_active.py"
    stub.write_text(executor_body, encoding="utf-8")
    return skills / "solar-async-tasks" / "scripts" / "execute_active.sh"


def test_exit_20_re_queues_the_parent_instead_of_completing_it(tmp_path):
    root = make_root(tmp_path)
    write_parent(root, extra='subtask_ids: "k1=child-1,k2=child-2"\n')
    wrapper = _worker_tree(tmp_path, "#!/usr/bin/env python3\nimport sys\nsys.exit(20)\n")

    proc = run_bash(wrapper, root, {"SOLAR_WORKSPACE": str(tmp_path)}, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (root / "completed" / "parent.md").exists()
    parked = root / "queued" / "parent.md"
    assert parked.exists()
    text = parked.read_text(encoding="utf-8")
    assert "status: queued" in text
    assert 'blocked_by_task_ids: "child-1,child-2"' in text


def test_exit_20_with_an_empty_manifest_is_an_error_not_a_completion(tmp_path):
    root = make_root(tmp_path)
    write_parent(root)
    wrapper = _worker_tree(tmp_path, "#!/usr/bin/env python3\nimport sys\nsys.exit(20)\n")

    proc = run_bash(wrapper, root, {"SOLAR_WORKSPACE": str(tmp_path)}, timeout=60)
    assert proc.returncode == 1
    assert "empty manifest" in proc.stdout + proc.stderr
    assert not (root / "completed" / "parent.md").exists()
    assert (root / "active" / "parent.md").exists()


def test_exit_0_still_completes_the_task(tmp_path):
    root = make_root(tmp_path)
    write_parent(root)
    wrapper = _worker_tree(tmp_path, "#!/usr/bin/env python3\n")

    proc = run_bash(wrapper, root, {"SOLAR_WORKSPACE": str(tmp_path)}, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (root / "completed" / "parent.md").exists()


# --- the whole loop, with an isolated provider -----------------------------

ROUTER_E2E = '''#!/usr/bin/env python3
"""Stand-in provider: answers as the parent or as a child, from the prompt."""
import json, sys

payload = json.loads(sys.stdin.read() or "{}")
text = payload.get("text", "")
if "## Subtask results" in text:
    reply = ("Contrasté las dos revisiones.\\n"
             "<delivery>Revisado por dos vías: coinciden en el diagnóstico.</delivery>")
elif "SOY EL PADRE" in text:
    reply = ("Reparto el trabajo.\\n<subtasks>\\n" + json.dumps([
        {"title": "Revisa A", "body": "Mira la parte A y responde."},
        {"title": "Revisa B", "body": "Mira la parte B y responde."},
    ]) + "\\n</subtasks>")
else:
    reply = "Hecho: " + ("parte A" if "parte A" in text else "parte B")
print(json.dumps({"status": "success", "reply_text": reply, "provider_used": "codex"}))
'''


# --- the child's identity and the object it inherits -----------------------

ROUTER_RECORDER = '''#!/usr/bin/env python3
"""Stand-in provider that writes down the prompt it was given."""
import json, os, pathlib, sys

payload = json.loads(sys.stdin.read() or "{}")
pathlib.Path(os.environ["PROMPT_FILE"]).write_text(payload.get("text", ""), encoding="utf-8")
print(json.dumps({"status": "success", "reply_text": "hecho", "provider_used": "codex"}))
'''


def _scripts_tree(tmp_path):
    """A working copy of both skills' scripts, for tests that swap one script."""
    skills = tmp_path / "skills"
    shutil.copytree(SCRIPTS, skills / "solar-async-tasks" / "scripts")
    shutil.copytree(SCRIPTS.parent.parent / "solar-router" / "scripts",
                    skills / "solar-router" / "scripts", dirs_exist_ok=True)
    _ensure_framework(skills)
    return skills / "solar-async-tasks" / "scripts"


def read_title(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


# --- create.sh's own contract for the two identity flags -------------------

def _create(root, *args, tmp_path=None):
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "create.sh"), *args],
        capture_output=True, text=True, timeout=60,
        env=env_for(root),
    )
    if proc.returncode == 0:
        mirror(root)
    return proc


def test_create_writes_the_child_identity_into_the_published_file(tmp_path):
    root = make_root(tmp_path)
    body = tmp_path / "child.md"
    body.write_text("Revisa la parte A.\n", encoding="utf-8")

    proc = _create(root, "--queued", "--parent-task-id", "parent-0001-aaaa",
                   "--subtask-key", "parent00-1-deadbeef", "--body-file", str(body), "Uno")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    created = children_files(root)
    assert len(created) == 1
    text = created[0].read_text(encoding="utf-8")
    # In the file as published, not added by a later write.
    assert 'parent_task_id: "parent-0001-aaaa"' in text
    assert 'subtask_key: "parent00-1-deadbeef"' in text
    head = text.split("---")[1]
    assert "parent_task_id:" in head and "subtask_key:" in head
    # A child still does not notify.
    assert "notify_when" not in text


def test_create_refuses_the_identity_flags_without_queued(tmp_path):
    root = make_root(tmp_path)
    proc = _create(root, "--parent-task-id", "parent-0001-aaaa", "Uno")
    assert proc.returncode == 1
    assert "require --queued" in proc.stderr
    assert not list((root / "drafts").glob("*.md"))

    proc = _create(root, "--subtask-key", "k1", "Uno")
    assert proc.returncode == 1
    assert "require --queued" in proc.stderr
    assert not list((root / "drafts").glob("*.md"))


# --- what the provider writes cannot become frontmatter --------------------

def test_a_title_cannot_inject_frontmatter(tmp_path):
    root = make_root(tmp_path)
    body = tmp_path / "child.md"
    body.write_text("x\n", encoding="utf-8")
    hostile = 'Uno"\nnotify_when: completed\norigin_chat_id: "456'

    proc = _create(root, "--queued", "--body-file", str(body), hostile)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    text = children_files(root)[0].read_text(encoding="utf-8")
    # The hostile text survives as one quoted scalar; what must not exist is a
    # frontmatter *line* it invented.
    keys = [line.split(":", 1)[0] for line in text.split("\n---", 1)[0].splitlines()
            if ":" in line]
    assert "notify_when" not in keys
    assert "origin_chat_id" not in keys
    assert len([k for k in keys if k == "title"]) == 1


def test_a_multiline_title_is_rejected_at_the_boundary(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    proc = run_executor(task, root, block([
        {"title": 'Uno"\nnotify_when: completed', "body": "x"},
    ]), tmp_path)
    assert proc.returncode == 1
    assert "spans more than one line" in (root / "error" / "parent.md").read_text(encoding="utf-8")


def test_create_refuses_an_unknown_priority(tmp_path):
    root = make_root(tmp_path)
    proc = _create(root, "--queued", "--priority", "urgent\nnotify_when: completed", "Uno")
    assert proc.returncode == 1
    assert "must be high, normal or low" in proc.stderr
    assert not list(root.rglob("*.md"))


def test_an_accented_title_stays_readable(tmp_path):
    """The escaping stops injection; it must not flatten the alphabet."""
    root = make_root(tmp_path)
    body = tmp_path / "child.md"
    body.write_text("x\n", encoding="utf-8")

    assert _create(root, "--queued", "--body-file", str(body), "Informe ñoño").returncode == 0
    text = children_files(root)[0].read_text(encoding="utf-8")
    assert 'title: "Informe ñoño"' in text
    assert "\\u00f1" not in text


# --- a parent that was never parked does not synthesize early --------------

def test_a_complete_manifest_with_running_children_waits_again(tmp_path):
    """The worker died between the reserved exit code and await_subtasks.sh."""
    root = make_root(tmp_path)
    child = root / "queued" / "uno.md"
    child.write_text(
        '---\nid: "child-1"\ntitle: "Uno"\nstatus: queued\nsubtask_key: "k1"\n---\n\n# Uno\n',
        encoding="utf-8",
    )
    task = write_parent(root, extra='subtask_ids: "k1=child-1"\n')

    marker = tmp_path / "router-was-called"
    proc = run_executor(task, root, "lo que sea", tmp_path, marker=marker)

    assert proc.returncode == 20, proc.stdout + proc.stderr
    assert not marker.exists(), "the provider must not synthesize over unfinished children"
    assert "## Subtask results" not in task.read_text(encoding="utf-8")


def test_a_missing_child_does_not_hold_the_parent_forever(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root, extra='subtask_ids: "k1=child-gone"\n')
    assert run_executor(task, root, "done", tmp_path).returncode == 0
    assert "### k1 — missing" in task.read_text(encoding="utf-8")


def test_the_shell_re_queues_a_parent_that_was_never_parked(tmp_path):
    """The same window, through execute_active.sh: it must end in queued/."""
    scripts = _scripts_tree(tmp_path)
    marker = tmp_path / "router-was-called"
    (scripts.parent.parent / "solar-router" / "scripts" / "run_router.py").write_text(
        ROUTER_STUB, encoding="utf-8")

    root = make_root(tmp_path)
    (root / "queued" / "uno.md").write_text(
        '---\nid: "child-1"\ntitle: "Uno"\nstatus: queued\nsubtask_key: "k1"\n---\n\n# Uno\n',
        encoding="utf-8",
    )
    write_parent(root, extra='subtask_ids: "k1=child-1"\n')

    proc = run_bash(
        scripts / "execute_active.sh", root,
        {"SOLAR_WORKSPACE": str(tmp_path), "STUB_MARKER": str(marker),
         "STUB_REPLY": "no deberia llamarse"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not marker.exists()
    assert not (root / "completed" / "parent.md").exists()
    parked = root / "queued" / "parent.md"
    assert parked.exists(), proc.stdout
    assert 'blocked_by_task_ids: "child-1"' in parked.read_text(encoding="utf-8")


def test_the_childs_own_result_heading_is_not_repeated(tmp_path):
    root = make_root(tmp_path)
    _finished_child(root, "completed", "uno", "child-1", "k1", "completed",
                    "# Async Task Execution\n\n- outcome: success\n\n## Result\n\n"
                    "## Result\n\nrevisé A\n")
    task = write_parent(root, extra='subtask_ids: "k1=child-1"\n')

    assert run_executor(task, root, "done", tmp_path).returncode == 0
    section = task.read_text(encoding="utf-8").split("## Subtask results", 1)[1]
    assert "### k1 — completed\n\nrevisé A" in section
    assert "## Result" not in section
