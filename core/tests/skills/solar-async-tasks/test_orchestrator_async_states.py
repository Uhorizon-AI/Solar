"""How a tick of the orchestrator reads the answer of ensure_async_tasks.sh.

The real orchestrator, pass-stamp writer and state run in a fixture install whose async-tasks `ensure`
is a stub that answers a chosen code, and whose gateway and host `ensure` scripts only leave a marker.
Nothing starts a service, probes the network (the gateway probe is pointed at a non-loopback name and
an empty run directory) or touches the machine runtime.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from supervisor_support import CORE_ROOT  # first: it puts the skills on sys.path

SKILLS = CORE_ROOT / "skills"


def _fixture_install(tmp: Path, ensure_body: str) -> Path:
    root = tmp / "solar-root"
    skills = root / "core" / "skills"
    skills.mkdir(parents=True)
    stubbed = {"solar-async-tasks": {"ensure_async_tasks.sh": ensure_body},
               "solar-gateway": {"ensure_transport_gateway.sh": f'#!/usr/bin/env bash\necho ran >"{tmp}/gateway-ran"\n'},
               "solar-app": {"ensure_host.sh": f'#!/usr/bin/env bash\necho ran >"{tmp}/host-ran"\n'}}
    for entry in SKILLS.iterdir():
        if entry.name in stubbed:
            folder = skills / entry.name / "scripts"
            folder.mkdir(parents=True)
            for script in (entry / "scripts").iterdir():           # everything real except the one stubbed script
                if script.name not in stubbed[entry.name]:
                    (folder / script.name).symlink_to(script)
            for name, body in stubbed[entry.name].items():
                (folder / name).write_text(body)
                (folder / name).chmod(0o755)
        else:
            (skills / entry.name).symlink_to(entry)
    return root


@pytest.mark.parametrize("code, stamped, tick_code", [
    (0, "ok", 0), (10, "starting", 0), (20, "blocked", 1), (1, "failed", 1), (7, "failed", 1)])
def test_each_answer_of_ensure_becomes_its_own_stamp_and_the_rest_of_the_tick_still_runs(rig, code, stamped, tick_code):
    install = _fixture_install(rig.tmp, f'#!/usr/bin/env bash\necho \'{{"state":"x"}}\'\nexit {code}\n')
    (rig.workspace / ".env").write_text("SOLAR_SYSTEM_FEATURES=async-tasks,transport-gateway,host\n")
    env = {**rig.env, "SOLAR_ROOT": str(install), "SOLAR_SYSTEM_LOCK_DIR": str(rig.tmp / "tick.lock"),
           "SOLAR_GATEWAY_RUN_DIR": str(rig.tmp / "gateway-run"), "SOLAR_HTTP_HOST": "gateway.invalid"}
    tick = subprocess.run(["bash", str(install / "core" / "skills" / "solar-system" / "scripts" / "run_orchestrator.sh"),
                           "--once"], env=env, capture_output=True, text=True, timeout=90, cwd=rig.workspace)
    stamp = json.loads((rig.runtime / "system" / "pass-stamp.json").read_text())
    assert stamp["features"]["async-tasks"] == stamped, tick.stdout + tick.stderr
    assert tick.returncode == tick_code, tick.stdout + tick.stderr
    assert (rig.tmp / "gateway-ran").exists() and (rig.tmp / "host-ran").exists(), \
        "the gateway and the host are processed whatever async-tasks answered"
    assert stamp["features"]["transport-gateway"] == "ok" and stamp["features"]["host"] == "ok"
    if code == 10:
        assert "failure" not in tick.stdout.lower().replace("0 failure", "")      # starting adds no failure
        assert "starting" in tick.stdout
    if code in (20, 1, 7):
        assert "finished with 1 failure" in tick.stderr


def test_check_orchestrator_reports_the_supervisor_by_state(rig):
    install = _fixture_install(rig.tmp, "#!/usr/bin/env bash\nexit 0\n")
    (rig.workspace / ".env").write_text("SOLAR_SYSTEM_FEATURES=async-tasks\n")
    (install / "core" / "skills" / "solar-app" / "scripts" / "check_host.sh").unlink(missing_ok=True)
    env = {**rig.env, "SOLAR_ROOT": str(install), "HOME": str(rig.tmp / "home")}
    (rig.tmp / "home" / "Library" / "LaunchAgents").mkdir(parents=True)
    (rig.tmp / "bin").mkdir()
    for name, rc in (("launchctl", 0), ("pgrep", 1)):
        (rig.tmp / "bin" / name).write_text(f"#!/bin/sh\nexit {rc}\n")
        (rig.tmp / "bin" / name).chmod(0o755)
    env["PATH"] = f"{rig.tmp / 'bin'}:{env['PATH']}"
    check = install / "core" / "skills" / "solar-system" / "scripts" / "check_orchestrator.sh"

    def run():
        return subprocess.run(["bash", str(check)], env=env, capture_output=True, text=True, timeout=90, cwd=rig.workspace).stdout

    absent = run()
    assert "supervisor:  absent not_running" in absent and "Feature: async-tasks" in absent
    (rig.runtime / "maintenance.json").write_text(json.dumps(dict(operation="update")))
    assert "supervisor:  blocked maintenance" in run()
    (rig.runtime / "maintenance.json").unlink()
    assert rig.script("ensure_async_tasks.sh").returncode == 0
    ready = run()
    assert "supervisor:  ready" in ready
    # the supervisor's own files are never offered as orphan locks to remove
    assert "supervisor.lock" not in ready.replace("never supervisor*.lock", "")
