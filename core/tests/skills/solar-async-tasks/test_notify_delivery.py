"""Delivery failure evidence and terminal task notifications, with a local sender."""
import os
import subprocess
from pathlib import Path

import pytest

from queue_mirror import env_for, mirror, seed, task_id_of

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
    env = env_for(root, {**os.environ, 'SOLAR_WORKSPACE': str(workspace), 'SOLAR_ROOT': str(install),
                         'TELEGRAM_CHAT_ID': '456', 'TELEGRAM_ALLOWED_CHAT_IDS': '456',
                         'TELEGRAM_BOT_TOKEN': 'fake'})
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
    root = path.parent.parent
    seed(root)
    result = subprocess.run(
        ['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(path)],
        env=env_for(root, env), text=True, capture_output=True, timeout=10,
    )
    mirror(root)
    return result


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
    assert (workspace / 'sent.log').read_text().count('Task completed') == 1


@pytest.mark.parametrize('body,timeout', [('exit 3', '5'), ('sleep 3', '1')])
def test_executor_failure_and_timeout_notify_origin(tmp_path, body, timeout):
    workspace, root, env = fixture_env(tmp_path)
    command = workspace / 'planets/test/skills/demo/scripts/run.sh'
    command.parent.mkdir(parents=True)
    command.write_text('#!/bin/bash\n' + body + '\n')
    command.chmod(0o755)
    task_file(root, 'active', 'executor: local\n'
              f'local_command: bash {command}\nlocal_timeout: {timeout}\n')
    seed(root)
    result = subprocess.run(['bash', str(SCRIPTS / 'execute_active.sh'), '--once'],
                            env=env_for(root, env), text=True, capture_output=True, timeout=15)
    mirror(root)
    assert result.returncode == 1, result.stdout + result.stderr
    failed = root / 'error/delivery.md'
    assert 'notify_delivered: true' in failed.read_text()
    assert 'Task failed' in (workspace / 'sent.log').read_text()
    assert 'error_code' not in (workspace / 'sent.log').read_text()


def test_cleanup_failure_notifies_origin(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task_file(root, 'active', 'cleanup_required: true\nresources: demo\n')
    hook = root / 'hooks/demo/post_complete.sh'
    hook.parent.mkdir(parents=True)
    hook.write_text('#!/bin/bash\nexit 1\n')
    hook.chmod(0o755)
    seed(root)
    result = subprocess.run(['bash', str(SCRIPTS / 'complete.sh'), 'delivery'],
                            env=env_for(root, env), text=True, capture_output=True, timeout=15)
    mirror(root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'notify_delivered: true' in (root / 'error/delivery.md').read_text()
    assert 'Task failed' in (workspace / 'sent.log').read_text()


def test_notification_is_sent_as_plain_text(tmp_path):
    """Regression: a title with `_` made Telegram reject a Markdown notify (HTTP 400)."""
    workspace, root, env = fixture_env(tmp_path)
    sender = Path(env['SOLAR_ROOT']) / 'core/skills/solar-telegram/scripts/send_telegram.sh'
    sender.write_text('#!/bin/bash\nprintf "%s|%s\\n" "${TELEGRAM_PARSE_MODE:-}" "$1" '
                      '>> "$SOLAR_WORKSPACE/sent.log"\n')
    task = task_file(root)
    task.write_text(task.read_text().replace('title: "Delivery"',
                                             'title: "Review 2026-09-16_audit.md"'))
    (workspace / '.env').write_text('TELEGRAM_PARSE_MODE=Markdown\n')
    assert notify(task, {**env, 'TELEGRAM_PARSE_MODE': 'MarkdownV2'}).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert sent.startswith('none|Task completed: Review 2026-09-16_audit.md')


def test_notification_points_at_result_path(tmp_path):
    """With result_path set by the executor, the notify links the result, not the task."""
    workspace, root, env = fixture_env(tmp_path)
    log = root / 'logs' / 'delivery.log'
    log.parent.mkdir(exist_ok=True)
    log.write_text('# Async Task Execution\n\n## Result\n\nall good\n')
    task = task_file(root, extra=f'result_path: "{log}"\n')
    assert notify(task, env).returncode == 0
    assert str(log) in (workspace / 'sent.log').read_text()


def test_notify_when_failed_reports_failure_with_its_reason_and_not_completion(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    failed = task_file(root, 'error', '')
    failed.write_text(failed.read_text().replace('notify_when: completed', 'notify_when: "failed"')
                      + '\n## Execution Error\n- error_code: provider_quota\n- error: quota exceeded\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Task failed' in sent and 'Reason: provider_quota' in sent
    assert 'quota exceeded' not in sent
    done = task_file(root, 'completed', '')
    done.write_text(done.read_text().replace('notify_when: completed', 'notify_when: "failed"'))
    assert notify(done, env).returncode == 0
    assert 'Task completed' not in (workspace / 'sent.log').read_text()


def test_notify_when_completed_alone_still_reports_failure_without_the_reason(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    failed = task_file(root, 'error', '')
    failed.write_text(failed.read_text() + '\n## Execution Error\n- error: secret path /x\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Task failed' in sent and 'Reason' not in sent


def test_a_new_claim_clears_the_notice_record_so_each_run_notifies_once(tmp_path):
    import solar_state
    _, root, env = fixture_env(tmp_path)
    task = task_file(root, 'queued', 'recurring: true\nnotify_delivered: true\nnotify_status: delivered\n')
    seed(root)
    with solar_state.session() as store:
        tid = task_id_of(task)
        store.task_claim(tid, 'worker')
        pairs = dict(store.task_get(tid)['frontmatter'])
    assert 'notify_delivered' not in pairs and 'notify_status' not in pairs
    assert pairs.get('notify_run', '').strip()


def _failed_with(root, env, error_section):
    failed = task_file(root, 'error', '')
    failed.write_text(failed.read_text().replace('notify_when: completed', 'notify_when: "failed"')
                      + '\n## Execution Error\n' + error_section)
    return failed


def test_reason_is_a_machine_code_and_never_the_provider_text(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    failed = _failed_with(root, env, '- error_code: router_crashed\n- error: token sk-123 at /Users/x/secret.md\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: router_crashed' in sent
    assert 'sk-123' not in sent and '/Users/x' not in sent


@pytest.mark.parametrize('section', ['- error: only free text with sk-123\n',
                                     '- error_code: see https://x.example/?t=sk-123\n',
                                     '- error_code: ' + 'a' * 80 + '\n'])
def test_a_missing_or_malformed_code_is_reported_as_unknown(tmp_path, section):
    workspace, root, env = fixture_env(tmp_path)
    failed = _failed_with(root, env, section)
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: unknown' in sent and 'sk-123' not in sent and 'x.example' not in sent


def test_two_notifiers_for_the_same_run_send_one_notice(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    sender = Path(env['SOLAR_ROOT']) / 'core/skills/solar-telegram/scripts/send_telegram.sh'
    sender.write_text('#!/bin/bash\nsleep 1\nprintf "%s\\n" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n')
    task = task_file(root, 'error', '')
    task.write_text(task.read_text().replace('notify_when: completed', 'notify_when: "failed"')
                    + '\n## Execution Error\n- error_code: boom\n')
    seed(root)
    run_env = env_for(root, {**env, 'TMPDIR': str(tmp_path)})
    cmd = ['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)]
    procs = [subprocess.Popen(cmd, env=run_env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(2)]
    assert [p.wait(timeout=30) for p in procs] == [0, 0]
    assert (workspace / 'sent.log').read_text().count('Task failed') == 1


def test_a_notice_recorded_for_an_earlier_run_does_not_silence_this_run(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'completed', 'notify_run: run-2\nnotify_delivered: true\n'
                     'notify_delivered_run: run-1\n')
    assert notify(task, env).returncode == 0
    assert (workspace / 'sent.log').read_text().count('Task completed') == 1
    assert 'notify_delivered_run: run-2' in task.read_text()


@pytest.mark.parametrize('when,sent', [('completed,failed', False), ('blocked', True), ('', True),
                                       ('completed', True)])
def test_the_approval_wait_notice_honours_blocked(tmp_path, when, sent):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'queued', '')
    task.write_text(task.read_text().replace('notify_when: completed', f'notify_when: "{when}"'))
    seed(root)
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task), '--waiting'],
                            env=env_for(root, env), text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    log = workspace / 'sent.log'
    assert (log.exists() and 'Waiting for your approval' in log.read_text()) is sent


def test_a_lock_that_is_never_released_is_recorded_not_dropped(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'completed', '')
    (tmp_path / f'solar-notify-{task_id_of(task)}.lock').mkdir()
    seed(root)
    # a wait of 150 s is too slow for a test: shorten it through a seq stub
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'seq').write_text('#!/bin/bash\necho 1\n')
    (stub / 'seq').chmod(0o755)
    (stub / 'sleep').write_text('#!/bin/bash\nexit 0\n')
    (stub / 'sleep').chmod(0o755)
    run_env = env_for(root, {**env, 'TMPDIR': str(tmp_path), 'PATH': f'{stub}:{os.environ["PATH"]}'})
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=run_env, text=True, capture_output=True, timeout=20)
    mirror(root)
    assert result.returncode == 1 and 'notify_lock_timeout' in result.stderr
    assert 'notify_error: notify_lock_timeout' in task.read_text()
    assert not (workspace / 'sent.log').exists()
