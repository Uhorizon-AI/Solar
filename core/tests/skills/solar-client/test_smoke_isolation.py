"""Run the real smoke CLI scenarios against an occupied caller runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

CORE = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("fail_reinit", [False, True])
def test_smoke_ignores_caller_runtime_and_reports_reinit_errors(tmp_path, fail_reinit):
    install = tmp_path / "source"
    # Keep the real CLI, state, sync and bundle implementation. Shell unit suites
    # are checked separately; do not nest those suites inside this regression.
    shutil.copytree(CORE, install / "core", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    support = install / "core/tests/support"
    support.mkdir(parents=True)
    shutil.copy2(CORE / "tests/support/shell_runtime_guard.sh", support)
    for folder, names in {
        "solar-paths": ["test_resolve_solar_paths.sh", "test_solar_paths_py.sh"],
        "solar-client": ["test_client_upgrade.sh", "test_client_manifest.sh", "test_client_bundle.sh",
                         "test_sync_exclude.sh", "test_sync_codex_agents.sh", "test_doctor_port.sh",
                         "test_client_update.sh"],
    }.items():
        target = install / "core/tests/skills" / folder
        target.mkdir(parents=True)
        for name in names:
            (target / name).write_text("#!/bin/bash\nexit 0\n")
    if fail_reinit:
        cli = install / "core/skills/solar-client/scripts/solar"
        code = cli.read_text()
        code = code.replace('set -euo pipefail', '''set -euo pipefail
if [[ "${1:-} ${2:-}" == 'client init' && -f .env ]]; then
  echo 'injected re-init refusal' >&2
  exit 23
fi''', 1)
        cli.write_text(code)
    # A real, deliberately foreign ownership record must never be reclaimed.
    runtime = tmp_path / "caller-runtime"
    runtime.mkdir()
    caller = tmp_path / "caller-workspace"
    caller.mkdir()
    owner = runtime / "workspace-owner.json"
    owner.write_text(json.dumps({"workspace_id": "foreign-owner", "path": str(caller),
                                 "claimed_at": "2026-10-18T00:00:00Z"}) + "\n")
    original = owner.read_bytes()
    sentinel = install / ".cursor/skills/keep"
    sentinel.mkdir(parents=True)
    env = os.environ.copy()
    env.update(SOLAR_ROOT=str(install), SOLAR_WORKSPACE=str(tmp_path / "caller-workspace"),
               SOLAR_RUNTIME_ROOT=str(runtime), SOLAR_APP_DATA=str(tmp_path / "caller-app"),
               SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE="host,gateway",
               SOLAR_CLIENT_LAUNCHCTL="/bin/launchctl")
    result = subprocess.run(
        ["bash", str(install / "core/skills/solar-client/scripts/smoke-solar-client.sh"), str(install)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    output = result.stdout + result.stderr
    assert owner.read_bytes() == original
    assert sorted(p.name for p in runtime.iterdir()) == ["workspace-owner.json"]
    assert sentinel.is_dir(), "upgrade must not prune the source install"
    assert not (tmp_path / "caller-app").exists()
    assert "PASS: init: settings+sun" in output, output
    assert "PASS: re-init preserves .env" in output, output
    assert "PASS: solar client sync after init" in output, output
    assert "PASS: update --bundle on install without .git" in output, output
    assert "FAIL: re-init overwrote .env" not in output
    if fail_reinit:
        assert result.returncode == 1, output
        assert "FAIL: solar client re-init" in output
        assert "injected re-init refusal" in output
        assert "FAIL=1" in output
    else:
        assert result.returncode == 0, output
        assert "FAIL=0" in output
