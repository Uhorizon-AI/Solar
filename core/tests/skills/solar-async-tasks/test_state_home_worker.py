"""The worker resolves a task's state home and hands it to the router (issue #175)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_subtask_worker import EXECUTE, ROUTER_STUB, make_root, task_id_of  # noqa: E402  (sets sys.path)
import solar_state  # noqa: E402
from queue_mirror import seed, mirror, env_for  # noqa: E402

PACKET_STUB = ROUTER_STUB.replace("sys.stdin.read()", "packet = json.loads(sys.stdin.read())").replace(
    'write_text("called",', "write_text(json.dumps(packet),")


def run(tmp_path, extra_fields, skill_front="state_home: true\n", create_skill=True):
    root = make_root(tmp_path)
    seed(root)
    with solar_state.session() as store:
        task = store.task_create([("title", '"Probe"'), ("planet", '"p"'), *extra_fields],
                                 "\n# Probe\n\nWrite the state.\n")
        store.task_approve(task)
        store.task_claim_detail(task, "test")
    mirror(root)
    router = tmp_path / "router_stub.py"
    router.write_text(PACKET_STUB, encoding="utf-8")
    marker = tmp_path / "packet.json"
    # The worker is a subprocess: it must not create state homes in the real app data.
    env = env_for(root, {**os.environ, "STUB_REPLY": "done", "STUB_MARKER": str(marker),
                         "SOLAR_APP_DATA": str(tmp_path / "app-data")})
    workspace = Path(env["SOLAR_WORKSPACE"])
    if create_skill:
        skill = workspace / "planets" / "p" / "skills" / "watch"
        skill.mkdir(parents=True, exist_ok=True)  # the owner workspace is shared across tests
        (skill / "SKILL.md").write_text(f"---\nname: watch\ndescription: x\n{skill_front}---\nbody\n")
    proc = subprocess.run([sys.executable, str(EXECUTE), task_id_of(root / "active" / f"{task}.md"), str(router)],
                          capture_output=True, text=True, env=env, timeout=120)
    mirror(root)
    return proc, marker, root, task


def test_without_state_home_the_router_request_has_none(tmp_path):
    proc, marker, *_ = run(tmp_path, [])
    assert proc.returncode == 0, proc.stderr
    assert "state_home" not in json.loads(marker.read_text())


def test_declared_state_home_is_created_and_sent_to_the_router(tmp_path):
    proc, marker, *_ = run(tmp_path, [("state_home", '"watch"')])
    assert proc.returncode == 0, proc.stderr
    # names only: the router derives the folder, no path travels in the request
    sent = json.loads(marker.read_text())["state_home"]
    assert {k: sent[k] for k in ("planet", "skill")} == {"planet": "p", "skill": "watch"}
    assert set(sent) == {"planet", "skill", "workspace"}
    home = Path(tmp_path / "app-data" / "Solar" / "planets")
    assert any(d.name == "watch" for d in home.glob("*/watch"))


def test_skill_that_did_not_opt_in_fails_the_task_and_never_calls_the_router(tmp_path):
    proc, marker, root, task = run(tmp_path, [("state_home", '"watch"')], skill_front="")
    assert proc.returncode == 1
    assert not marker.exists()
    assert "state_home_not_declared" in (root / "error" / f"{task}.md").read_text()


def test_unknown_skill_fails_clearly(tmp_path):
    proc, marker, root, task = run(tmp_path, [("state_home", '"ghost"')])
    assert proc.returncode == 1 and not marker.exists()
    assert "state_home_invalid" in (root / "error" / f"{task}.md").read_text()


def test_state_home_is_part_of_the_approval():
    """Changing it after approval is a different task; not declaring it leaves old digests alone."""
    base = [["title", ' "T"'], ["planet", ' "p"']]
    plain = solar_state.material_digest(base, "body")
    declared = solar_state.material_digest(base + [["state_home", ' "watch"']], "body")
    other = solar_state.material_digest(base + [["state_home", ' "other"']], "body")
    assert plain != declared != other
    assert solar_state.material_digest(list(base), "body") == plain


@pytest.mark.parametrize("extra", [("origin_channel", '"app"'), ("origin_channel", '"voice"'), ("executor", '"local"')])
def test_tasks_that_cannot_hold_a_grant_fail_instead_of_ignoring_it(tmp_path, extra):
    fields = [("state_home", '"watch"'), extra]
    if extra[0] == "executor":
        fields.append(("local_command", '"bash planets/p/skills/watch/scripts/x.sh"'))
    proc, marker, root, task = run(tmp_path, fields)
    assert proc.returncode == 1 and not marker.exists()
    assert "state_home_invalid" in (root / "error" / f"{task}.md").read_text()
