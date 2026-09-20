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
    env = {**os.environ, "SOLAR_TASK_ROOT": str(root), "STUB_REPLY": reply}
    if marker:
        env["STUB_MARKER"] = str(marker)
    else:
        env.pop("STUB_MARKER", None)
    return subprocess.run(
        [sys.executable, str(EXECUTE), str(task), str(router),
         "parent-0001-aaaa", "Parent"],
        capture_output=True, text=True, env=env, timeout=120,
    )


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

def test_a_declaration_creates_the_children_and_asks_to_wait(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    proc = run_executor(task, root, block([
        {"title": "Uno", "body": "Revisa A"},
        {"title": "Dos", "body": "Revisa B", "provider": "claude"},
    ]), tmp_path)

    assert proc.returncode == 20, proc.stdout + proc.stderr
    pairs = manifest(task)
    assert len(pairs) == 2
    assert all("=" in pair and pair.split("=")[1] for pair in pairs)

    created = children_files(root)
    assert len(created) == 2
    bodies = [f.read_text(encoding="utf-8") for f in created]
    for text in bodies:
        assert 'parent_task_id: "parent-0001-aaaa"' in text
        assert "subtask_key:" in text
        # Only the parent speaks to the chat.
        assert "notify_when" not in text
        assert "origin_chat_id" not in text
        assert "delivery_expected" not in text
        # The object travels down unchanged.
        assert 'object: "el informe"' in text
        assert "priority: normal" in text
    assert any('provider: "claude"' in text for text in bodies)
    # Execution 1 owes no delivery.
    assert "## Delivery" not in task.read_text(encoding="utf-8")


def test_the_manifest_survives_and_the_task_is_not_moved(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    run_executor(task, root, block([{"title": "Uno", "body": "Revisa A"}]), tmp_path)
    # The executor never touches the queue: moving the parent is the shell's job.
    assert task.exists()
    assert "status: active" in task.read_text(encoding="utf-8")


def test_five_children_are_allowed(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    proc = run_executor(task, root, block([
        {"title": f"Hijo {i}", "body": f"Trabajo {i}"} for i in range(5)
    ]), tmp_path)
    assert proc.returncode == 20, proc.stdout + proc.stderr
    assert len(children_files(root)) == 5


# --- rejection is total and visible ---------------------------------------

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


def test_the_last_block_wins(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    reply = (
        "Así se declara:\n<subtasks>\n[{\"title\": \"Ejemplo\", \"body\": \"no\"}]\n</subtasks>\n"
        "Y esto es lo que quiero:\n" + block([{"title": "Real", "body": "sí"}])
    )
    assert run_executor(task, root, reply, tmp_path).returncode == 20
    created = children_files(root)
    assert len(created) == 1
    assert 'title: "Real"' in created[0].read_text(encoding="utf-8")


# --- depth is one, and one batch per request -------------------------------

def test_a_child_cannot_declare_grandchildren(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root, extra='parent_task_id: "some-parent"\n')
    proc = run_executor(task, root, block([{"title": "Nieto", "body": "no"}]), tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not children_files(root)
    assert "subtask_ids" not in task.read_text(encoding="utf-8")


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

def test_a_half_written_manifest_is_resumed_without_calling_the_provider(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    # State left by a run that died between the two children.
    (root / "subtasks").mkdir()
    (root / "subtasks" / "parent-0001-aaaa.json").write_text(json.dumps([
        {"title": "Uno", "body": "Revisa A", "provider": None},
        {"title": "Dos", "body": "Revisa B", "provider": None},
    ]), encoding="utf-8")
    existing = root / "queued" / "first.md"
    existing.write_text(
        '---\nid: "child-1"\ntitle: "Uno"\nstatus: queued\nsubtask_key: "k1"\n---\n\n# Uno\n',
        encoding="utf-8",
    )
    task.write_text(
        task.read_text(encoding="utf-8").replace(
            "status: active\n", 'status: active\nsubtask_ids: "k1=child-1,k2="\n'
        ),
        encoding="utf-8",
    )

    marker = tmp_path / "router-was-called"
    proc = run_executor(task, root, block([{"title": "No", "body": "no"}]), tmp_path, marker=marker)

    assert proc.returncode == 20, proc.stdout + proc.stderr
    assert not marker.exists(), "the provider must not be called while children are missing"
    pairs = manifest(task)
    assert len(pairs) == 2 and all(p.split("=")[1] for p in pairs)
    assert len(children_files(root)) == 2  # the one that existed, plus the missing one


def test_a_child_that_already_exists_is_not_created_twice(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    (root / "subtasks").mkdir()
    child = {"title": "Uno", "body": "Revisa A", "provider": None}
    (root / "subtasks" / "parent-0001-aaaa.json").write_text(json.dumps([child]), encoding="utf-8")

    # Same declaration ⇒ same key, computed the way the worker computes it.
    sys.path.insert(0, str(SCRIPTS))
    import execute_active  # noqa: E402
    key = execute_active.subtask_key("parent-0001-aaaa", 1, child["title"], child["body"])

    orphan = root / "queued" / "orphan.md"
    orphan.write_text(
        f'---\nid: "child-9"\ntitle: "Uno"\nstatus: queued\nsubtask_key: "{key}"\n---\n\n# Uno\n',
        encoding="utf-8",
    )
    task.write_text(
        task.read_text(encoding="utf-8").replace(
            "status: active\n", f'status: active\nsubtask_ids: "{key}="\n'
        ),
        encoding="utf-8",
    )

    proc = run_executor(task, root, "sin bloque", tmp_path)
    assert proc.returncode == 20, proc.stdout + proc.stderr
    assert len(children_files(root)) == 1
    assert manifest(task) == [f"{key}=child-9"]


# --- results come back through the worker ---------------------------------

def _finished_child(root, folder, name, task_id, key, status, log_body):
    path = root / folder / f"{name}.md"
    extra = ""
    if status == "completed":
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

def _worker_tree(tmp_path, executor_body):
    """A copy of the scripts with a stub executor, to test the wrapper itself."""
    skills = tmp_path / "skills"
    shutil.copytree(SCRIPTS, skills / "solar-async-tasks" / "scripts")
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

    proc = subprocess.run(
        ["bash", str(wrapper), "--once"], capture_output=True, text=True, timeout=60,
        env={**os.environ, "SOLAR_TASK_ROOT": str(root), "SOLAR_WORKSPACE": str(tmp_path)},
    )
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

    proc = subprocess.run(
        ["bash", str(wrapper), "--once"], capture_output=True, text=True, timeout=60,
        env={**os.environ, "SOLAR_TASK_ROOT": str(root), "SOLAR_WORKSPACE": str(tmp_path)},
    )
    assert proc.returncode == 1
    assert "empty manifest" in proc.stdout + proc.stderr
    assert not (root / "completed" / "parent.md").exists()
    assert (root / "active" / "parent.md").exists()


def test_exit_0_still_completes_the_task(tmp_path):
    root = make_root(tmp_path)
    write_parent(root)
    wrapper = _worker_tree(tmp_path, "#!/usr/bin/env python3\n")

    proc = subprocess.run(
        ["bash", str(wrapper), "--once"], capture_output=True, text=True, timeout=60,
        env={**os.environ, "SOLAR_TASK_ROOT": str(root), "SOLAR_WORKSPACE": str(tmp_path)},
    )
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


def test_a_request_with_subtasks_completes_end_to_end(tmp_path):
    """The closing criterion, run locally: declare, create, wait, serve, synthesize."""
    skills = tmp_path / "skills"
    shutil.copytree(SCRIPTS, skills / "solar-async-tasks" / "scripts")
    shutil.copytree(SCRIPTS.parent.parent / "solar-router" / "scripts",
                    skills / "solar-router" / "scripts", dirs_exist_ok=True)
    (skills / "solar-router" / "scripts" / "run_router.py").write_text(
        ROUTER_E2E, encoding="utf-8")

    install = tmp_path / "install"
    sender = install / "core/skills/solar-telegram/scripts/send_telegram.sh"
    sender.parent.mkdir(parents=True)
    sender.write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$SOLAR_TASK_ROOT/sent.log"\n',
                      encoding="utf-8")
    sender.chmod(0o755)

    root = make_root(tmp_path)
    parent = root / "queued" / "parent.md"
    parent.write_text(
        '---\nid: "parent-0001-aaaa"\ntitle: "Parent"\nstatus: queued\npriority: normal\n'
        'scheduled_time: "now"\nrecurring: false\n'
        'object: "el informe"\nscope: "solo lectura"\neffect: "un resumen"\n'
        'origin_channel: "telegram"\norigin_chat_id: "456"\nnotify_when: completed\n'
        'delivery_expected: true\n---\n\n# Parent\n\nSOY EL PADRE. Reparte el trabajo.\n',
        encoding="utf-8",
    )

    env = {**os.environ, "SOLAR_TASK_ROOT": str(root), "SOLAR_WORKSPACE": str(tmp_path),
           "SOLAR_ROOT": str(install), "TELEGRAM_CHAT_ID": "456",
           "TELEGRAM_ALLOWED_CHAT_IDS": "456", "TELEGRAM_BOT_TOKEN": "fake"}
    worker = skills / "solar-async-tasks" / "scripts" / "run_worker.sh"

    for _ in range(8):
        subprocess.run(["bash", str(worker), "--once"], capture_output=True, text=True,
                       env=env, timeout=120)
        if (root / "completed" / "parent.md").exists():
            break

    done = root / "completed" / "parent.md"
    assert done.exists(), sorted(p.name for p in root.rglob("*.md"))
    text = done.read_text(encoding="utf-8")

    # The children were created, ran, and came back through the worker.
    assert len(list((root / "completed").glob("*.md"))) == 3
    assert "## Subtask results" in text
    assert "Hecho: parte A" in text and "Hecho: parte B" in text
    # The parent synthesized and only the parent spoke to the chat.
    assert "coinciden en el diagnóstico" in text
    assert "coinciden en el diagnóstico" in (root / "sent.log").read_text(encoding="utf-8")
    assert (root / "sent.log").read_text(encoding="utf-8").count("Revisado por dos vías") == 1
    # The record of which children were this parent's survives completion.
    assert "subtask_ids:" in text


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
    return skills / "solar-async-tasks" / "scripts"


def test_the_object_reaches_the_child_in_its_prompt(tmp_path):
    """Frontmatter is stripped before the prompt: the scope must be in the body."""
    root = make_root(tmp_path)
    parent = write_parent(root)
    assert run_executor(parent, root, block([
        {"title": "Uno", "body": "Revisa la parte A."},
    ]), tmp_path).returncode == 20

    child = children_files(root)[0]
    # The child is picked up from queued/ like any other task.
    active_child = root / "active" / child.name
    child.rename(active_child)
    active_child.write_text(
        active_child.read_text(encoding="utf-8").replace("status: queued", "status: active"),
        encoding="utf-8",
    )

    router = tmp_path / "router_recorder.py"
    router.write_text(ROUTER_RECORDER, encoding="utf-8")
    prompt_file = tmp_path / "prompt.txt"
    proc = subprocess.run(
        [sys.executable, str(EXECUTE), str(active_child), str(router),
         "child-1", "Uno"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "SOLAR_TASK_ROOT": str(root), "PROMPT_FILE": str(prompt_file)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    prompt = prompt_file.read_text(encoding="utf-8")
    assert "## Object" in prompt
    assert "el informe" in prompt and "solo lectura" in prompt
    assert "a child cannot widen it" in prompt
    assert "$SOLAR_ROOT" in prompt
    assert "Revisa la parte A." in prompt
    # The frontmatter copy stays for checking, but it is not what was sent.
    assert "parent_task_id" not in prompt


def test_the_childs_identity_is_written_with_the_file_not_after_it(tmp_path):
    root = make_root(tmp_path)
    task = write_parent(root)
    assert run_executor(task, root, block([{"title": "Uno", "body": "x"}]), tmp_path).returncode == 20
    child = children_files(root)[0]
    text = child.read_text(encoding="utf-8")
    key = manifest(task)[0].split("=")[0]
    assert f'subtask_key: "{key}"' in text
    assert 'parent_task_id: "parent-0001-aaaa"' in text
    # Same write as the rest of the frontmatter: no partial file can exist.
    assert text.index("subtask_key:") < text.index("---", 4)


def test_a_crash_right_after_publishing_a_child_does_not_duplicate_it(tmp_path):
    """The window Codex found: create.sh publishes, then the worker dies."""
    scripts = _scripts_tree(tmp_path)
    (scripts.parent.parent / "solar-router" / "scripts" / "run_router.py").write_text(
        ROUTER_STUB, encoding="utf-8")
    real = scripts / "create_real.sh"
    (scripts / "create.sh").rename(real)
    (scripts / "create.sh").write_text(
        '#!/bin/bash\n'
        'bash "$(dirname "$0")/create_real.sh" "$@"\n'
        'rc=$?\n'
        # The child is now published in queued/ and runnable. Die here.
        'if [[ -n "${CRASH_AFTER_CREATE:-}" ]]; then kill -9 $PPID; fi\n'
        'exit $rc\n',
        encoding="utf-8",
    )
    executor = scripts / "execute_active.py"
    router = tmp_path / "router_stub.py"
    router.write_text(ROUTER_STUB, encoding="utf-8")

    root = make_root(tmp_path)
    task = write_parent(root)
    declaration = block([
        {"title": "Uno", "body": "Revisa A"},
        {"title": "Dos", "body": "Revisa B"},
    ])
    base = {**os.environ, "SOLAR_TASK_ROOT": str(root), "STUB_REPLY": declaration,
            "SOLAR_WORKSPACE": str(tmp_path)}
    argv = [sys.executable, str(executor), str(task), str(router), "parent-0001-aaaa", "Parent"]

    crashed = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                             env={**base, "CRASH_AFTER_CREATE": "1"})
    assert crashed.returncode != 0
    orphans = children_files(root)
    assert len(orphans) == 1
    # It carries its key already: this is what makes it reconcilable.
    assert "subtask_key:" in orphans[0].read_text(encoding="utf-8")
    # And the parent never got to record its id: without the key on the file,
    # the retry would have no way to tell this child from one it must create.
    assert manifest(task)[0].endswith("=")

    resumed = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=base)
    assert resumed.returncode == 20, resumed.stdout + resumed.stderr
    created = children_files(root)
    assert len(created) == 2, [f.name for f in created]
    titles = sorted(read_title(f) for f in created)
    assert titles == ["Dos", "Uno"]
    pairs = manifest(task)
    assert len(pairs) == 2 and all(p.split("=")[1] for p in pairs)


def read_title(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


# --- create.sh's own contract for the two identity flags -------------------

def _create(root, *args, tmp_path=None):
    return subprocess.run(
        ["bash", str(SCRIPTS / "create.sh"), *args],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "SOLAR_TASK_ROOT": str(root)},
    )


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
