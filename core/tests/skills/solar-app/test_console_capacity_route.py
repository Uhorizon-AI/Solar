"""The real console, on the harness's private port, serves the capacity projection of a runtime that
has a real supervisor. Nothing here uses port 9000, the machine runtime or a LaunchAgent."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CORE = Path(__file__).resolve().parents[3]
SCRIPTS = CORE / "skills" / "solar-async-tasks" / "scripts"


def _get(harness, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{harness.port}{path}", timeout=20) as response:
        return json.loads(response.read())


def _run(harness, script, *args):
    env = harness.env(SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="none", SOLAR_CLIENT_LAUNCHCTL="/bin/true")
    return subprocess.run(["bash", str(SCRIPTS / script), *args], env=env, cwd=harness.ws,
                          capture_output=True, text=True, timeout=60)


def test_the_console_projects_capacity_the_supervisor_and_the_configuration(harness):
    harness.claim_state()
    harness.start_real_console()
    quiet = _get(harness, "/api/console/capacity")
    assert quiet["capacity"]["global_capacity"] == 1 and quiet["capacity"]["used"] == 0
    assert quiet["supervisor"] is None and quiet["configuration"]["applied"]["revision"] == 0
    assert quiet["configuration"]["pending"] is False
    try:
        ensured = _run(harness, "ensure_async_tasks.sh")
        assert ensured.returncode == 0, ensured.stdout + ensured.stderr
        deadline = time.time() + 20
        while time.time() < deadline:
            shown = _get(harness, "/api/console/capacity")
            if shown["supervisor"] and shown["supervisor"]["fresh"] and shown["supervisor"]["reconciled"]:
                break
            time.sleep(0.2)
        assert shown["supervisor"]["state"] == "ready" and shown["supervisor"]["blocked"] == []
        health = _get(harness, "/api/console/health")             # the stamp vocabulary reaches the verdict
        assert health["verdict"]["verdict"] in ("calm", "fault", "unverified")
    finally:
        _run(harness, "stop_supervisor.sh", "--drain", "--timeout", "30")
