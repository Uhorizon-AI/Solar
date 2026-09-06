"""Delivery failure evidence and terminal task notifications, with a local sender."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / 'skills/solar-async-tasks/scripts'


def fixture_env(tmp_path):
    workspace = tmp_path / 'workspace'
    install = tmp_path / 'install'
    root = workspace / 'sun/runtime/async-tasks'
    (root / 'active').mkdir(parents=True)
    sender = install / 'core/skills/solar-telegram/scripts/send_telegram.sh'
    sender.parent.mkdir(parents=True)
    sender.write_text('#!/bin/bash\nif [[ "${FAIL_SEND:-}" == 1 ]]; then exit 7; fi\nprintf "%s\\n" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n')
    sender.chmod(0o755)
    env = {**os.environ, 'SOLAR_WORKSPACE': str(workspace), 'SOLAR_ROOT': str(install),
           'SOLAR_TASK_ROOT': str(root), 'TELEGRAM_CHAT_ID': '456',
           'TELEGRAM_ALLOWED_CHAT_IDS': '456', 'TELEGRAM_BOT_TOKEN': 'fake'}
    env.pop('FAIL_SEND', None)
    return workspace, root, env


def task_file(root, status='completed', extra=''):
    folder = root / status
    folder.mkdir(exist_ok=True)
    path = folder / 'delivery.md'
    path.write_text(f'---\nid: "delivery"\ntitle: "Delivery"\nstatus: {status}\n'
                    'notify_when: completed\norigin_chat_id: "456"\n' + extra + '---\n\n# Task\n')
    return path


def notify(path, env):
    return subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), str(path)],
                          env=env, text=True, capture_output=True, timeout=10)


def test_failed_delivery_recorded_and_successful_retry_deduplicated(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root)
    result = notify(task, {**env, 'FAIL_SEND': '1'})
    assert result.returncode == 1
    assert 'notify_status: failed' in task.read_text()
    assert 'notify_error: telegram_send_failed' in task.read_text()
    assert 'notify_delivered: true' not in task.read_text()
    assert notify(task, env).returncode == 0
    assert 'notify_status: delivered' in task.read_text()
    assert notify(task, env).returncode == 0
    assert (workspace / 'sent.log').read_text().count('Tarea completada') == 1


@pytest.mark.parametrize('body,timeout', [('exit 3', '5'), ('sleep 3', '1')])
def test_executor_failure_and_timeout_notify_origin(tmp_path, body, timeout):
    workspace, root, env = fixture_env(tmp_path)
    command = workspace / 'planets/test/skills/demo/scripts/run.sh'
    command.parent.mkdir(parents=True)
    command.write_text('#!/bin/bash\n' + body + '\n')
    command.chmod(0o755)
    task_file(root, 'active', 'executor: local\n'
              f'local_command: bash {command}\nlocal_timeout: {timeout}\n')
    result = subprocess.run(['bash', str(SCRIPTS / 'execute_active.sh'), '--once'],
                            env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 1, result.stdout + result.stderr
    failed = root / 'error/delivery.md'
    assert 'notify_delivered: true' in failed.read_text()
    assert 'ha fallado' in (workspace / 'sent.log').read_text()
    assert 'error_code' not in (workspace / 'sent.log').read_text()


def test_cleanup_failure_notifies_origin(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task_file(root, 'active', 'cleanup_required: true\nresources: demo\n')
    hook = root / 'hooks/demo/post_complete.sh'
    hook.parent.mkdir(parents=True)
    hook.write_text('#!/bin/bash\nexit 1\n')
    hook.chmod(0o755)
    result = subprocess.run(['bash', str(SCRIPTS / 'complete.sh'), 'delivery'],
                            env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'notify_delivered: true' in (root / 'error/delivery.md').read_text()
    assert 'ha fallado' in (workspace / 'sent.log').read_text()
