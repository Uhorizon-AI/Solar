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
                    'notify_when: completed,failed\norigin_chat_id: "456"\n' + extra + '---\n\n# Task\n')
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
    failed = task_file(root, 'error', 'failure_code: provider_quota\n')
    failed.write_text(failed.read_text().replace('notify_when: completed,failed', 'notify_when: "failed"')
                      + '\n## Execution Error\n- error_code: provider_quota\n- error: quota exceeded\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Task failed' in sent and 'Reason: provider_quota' in sent
    assert 'quota exceeded' not in sent
    done = task_file(root, 'completed', '')
    done.write_text(done.read_text().replace('notify_when: completed,failed', 'notify_when: "failed"'))
    assert notify(done, env).returncode == 0
    assert 'Task completed' not in (workspace / 'sent.log').read_text()


def test_failed_adds_only_the_machine_code_never_the_provider_text(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    failed = task_file(root, 'error', '')
    failed.write_text(failed.read_text() + '\n## Execution Error\n- error: secret path /x\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Task failed' in sent and 'Reason: unknown' in sent and 'secret' not in sent


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


def _failed_with(root, code, error_section):
    """A failed task whose stored `failure_code` is `code` (None: the failure stored none)."""
    failed = task_file(root, 'error', '' if code is None else f'failure_code: "{code}"\n')
    failed.write_text(failed.read_text().replace('notify_when: completed,failed', 'notify_when: "failed"')
                      + '\n## Execution Error\n' + error_section)
    return failed


def test_reason_is_a_machine_code_and_never_the_provider_text(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    failed = _failed_with(root, 'router_crashed', '- error_code: router_crashed\n- error: token sk-123 at /Users/x/secret.md\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: router_crashed' in sent
    assert 'sk-123' not in sent and '/Users/x' not in sent


@pytest.mark.parametrize('code', [None, 'see https://x.example/?t=sk-123', 'a' * 80])
def test_a_missing_or_malformed_code_is_reported_as_unknown(tmp_path, code):
    workspace, root, env = fixture_env(tmp_path)
    failed = _failed_with(root, code, '- error: only free text with sk-123\n')
    assert notify(failed, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: unknown' in sent and 'sk-123' not in sent and 'x.example' not in sent


def test_two_notifiers_for_the_same_run_send_one_notice(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    sender = Path(env['SOLAR_ROOT']) / 'core/skills/solar-telegram/scripts/send_telegram.sh'
    sender.write_text('#!/bin/bash\nsleep 1\nprintf "%s\\n" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n')
    task = task_file(root, 'error', 'failure_code: boom\n')
    task.write_text(task.read_text().replace('notify_when: completed,failed', 'notify_when: "failed"'))
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


@pytest.mark.parametrize('when', ['completed,failed', 'failed', '', 'completed'])
def test_the_approval_wait_notice_is_sent_whatever_notify_when_lists(tmp_path, when):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'queued', '')
    task.write_text(task.read_text().replace('notify_when: completed,failed', f'notify_when: "{when}"'))
    seed(root)
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task), '--waiting'],
                            env=env_for(root, env), text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'Waiting for your approval' in (workspace / 'sent.log').read_text()


def _notify_when(tmp_path, status, when, body_extra=''):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, status, body_extra)
    task.write_text(task.read_text().replace('notify_when: completed,failed', f'notify_when: "{when}"'))
    return workspace, root, env, task


@pytest.mark.parametrize('when,status,sent', [
    ('completed', 'completed', True), ('completed', 'error', True),    # a bare `completed` is what older tasks carry
    ('completed,-failed', 'completed', True), ('completed,-failed', 'error', False),   # completion only, asked for
    ('failed', 'completed', False), ('failed', 'error', True),
    ('completed,failed', 'completed', True), ('completed,failed', 'error', True),
    ('', 'completed', False), ('', 'error', False)])
def test_notify_when_selection_decides_what_is_announced(tmp_path, when, status, sent):
    workspace, root, env, task = _notify_when(tmp_path, status, when)
    assert notify(task, env).returncode == 0
    log = workspace / 'sent.log'
    assert log.exists() is sent


def test_reason_is_the_code_stored_with_the_failure_not_one_found_in_the_body(tmp_path):
    workspace, root, env, task = _notify_when(tmp_path, 'error', 'failed', 'failure_code: second_code\n')
    task.write_text(task.read_text() + '\n## Execution Error\n- error_code: first_code\n- error: one\n')
    assert notify(task, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: second_code' in sent and 'first_code' not in sent


def test_a_failure_without_a_code_does_not_borrow_the_one_of_an_earlier_attempt(tmp_path):
    """complete.sh fails a task on a cleanup error and writes no `## Execution Error`: the old section is stale."""
    workspace, root, env, task = _notify_when(tmp_path, 'error', 'failed')
    task.write_text(task.read_text() + '\n## Execution Error\n- error_code: old_attempt\n')
    assert notify(task, env).returncode == 0
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: unknown' in sent and 'old_attempt' not in sent


def test_a_failure_notice_for_an_earlier_run_sends_nothing(tmp_path):
    """The supervisor queued the notice for run-1; the task was claimed again (run-2) before it went out."""
    workspace, root, env, task = _notify_when(tmp_path, 'queued', 'completed,failed', 'notify_run: run-2\n')
    seed(root)
    stale = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                           env=env_for(root, {**env, 'SOLAR_NOTIFY_EXPECT_RUN': 'run-1',
                                              'SOLAR_NOTIFY_EXPECT_STATUS': 'error'}),
                           text=True, capture_output=True, timeout=10)
    assert stale.returncode == 0
    assert not (workspace / 'sent.log').exists(), 'announced a completion for a task that is not finished'
    assert 'notify_delivered: true' not in task.read_text()


def test_a_failure_notice_for_the_current_run_is_sent_and_recorded_for_that_run(tmp_path):
    workspace, root, env, task = _notify_when(tmp_path, 'error', 'failed', 'notify_run: run-1\n')
    seed(root)
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=env_for(root, {**env, 'SOLAR_NOTIFY_EXPECT_RUN': 'run-1',
                                               'SOLAR_NOTIFY_EXPECT_STATUS': 'error'}),
                            text=True, capture_output=True, timeout=10)
    mirror(root)
    assert result.returncode == 0, result.stderr
    assert 'notify_delivered_run: run-1' in task.read_text()
    assert 'Task failed and needs attention' in (workspace / 'sent.log').read_text()


def _hold_lock(tmp_path, task, seconds):
    """A live process that holds the task's notice lock, as a slow sender would."""
    lock = tmp_path / f'solar-notify-{task_id_of(task)}.flock'
    holder = subprocess.Popen(
        ['python3', '-c', 'import fcntl,sys,time;f=open(sys.argv[1],"a");fcntl.flock(f,fcntl.LOCK_EX);'
         'print("held",flush=True);time.sleep(float(sys.argv[2]))', str(lock), str(seconds)],
        stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'held'
    return holder


def test_a_lock_held_by_a_live_sender_is_never_taken_over_and_is_recorded(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'completed', '')
    holder = _hold_lock(tmp_path, task, 30)
    try:
        seed(root)
        # the lock file is old: age must not matter, only whether its holder is alive
        old = 1_600_000_000
        os.utime(tmp_path / f'solar-notify-{task_id_of(task)}.flock', (old, old))
        result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                                env=env_for(root, {**env, 'TMPDIR': str(tmp_path), 'SOLAR_NOTIFY_LOCK_WAIT': '3'}),
                                text=True, capture_output=True, timeout=20)
        mirror(root)
        assert result.returncode == 1 and 'notify_lock_timeout' in result.stderr
        assert 'notify_error: notify_lock_timeout' in task.read_text()
        assert not (workspace / 'sent.log').exists()
    finally:
        holder.kill()


def test_a_lock_whose_holder_died_does_not_block_the_next_sender(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'completed', '')
    holder = _hold_lock(tmp_path, task, 30)
    holder.kill()
    holder.wait()
    seed(root)
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=env_for(root, {**env, 'TMPDIR': str(tmp_path), 'SOLAR_NOTIFY_LOCK_WAIT': '3'}),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (workspace / 'sent.log').read_text().count('Task completed') == 1


def test_two_senders_at_once_send_one_notice(tmp_path):
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'completed', '')
    seed(root)
    run_env = env_for(root, {**env, 'TMPDIR': str(tmp_path)})
    procs = [subprocess.Popen(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                              env=run_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for _ in range(3)]
    for proc in procs:
        proc.communicate(timeout=30)
        assert proc.returncode == 0
    assert (workspace / 'sent.log').read_text().count('Task completed') == 1


def test_a_failure_notice_is_dropped_when_the_task_is_claimed_again_while_it_waits_for_the_lock(tmp_path):
    import solar_state
    workspace, root, env, task = _notify_when(tmp_path, 'error', 'failed', 'notify_run: run-1\n')
    seed(root)
    holder = _hold_lock(tmp_path, task, 30)
    try:
        proc = subprocess.Popen(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                                env=env_for(root, {**env, 'TMPDIR': str(tmp_path), 'SOLAR_NOTIFY_LOCK_WAIT': '20',
                                                   'SOLAR_NOTIFY_EXPECT_RUN': 'run-1',
                                                   'SOLAR_NOTIFY_EXPECT_STATUS': 'error'}),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import time
        time.sleep(2)
        with solar_state.session() as store:          # the next attempt claims the task while the notifier waits
            store.task_set(task_id_of(task), 'notify_run', 'run-2')
        holder.kill()
        proc.communicate(timeout=30)
        assert proc.returncode == 0
        assert not (workspace / 'sent.log').exists(), 'the notice of an earlier run reached the chat'
    finally:
        holder.kill()


def test_the_lock_is_released_when_the_notifier_dies_and_its_sender_does_not_keep_it(tmp_path):
    import signal
    import time
    workspace, root, env = fixture_env(tmp_path)
    sender = Path(env['SOLAR_ROOT']) / 'core/skills/solar-telegram/scripts/send_telegram.sh'
    slow = tmp_path / 'slow'
    slow.write_text('1')
    started_marker = tmp_path / 'sender-started'
    sender.write_text('#!/bin/bash\nif [[ -e ' + str(slow) + ' ]]; then touch ' + str(started_marker) + '; sleep 30; fi\n'
                      'printf "%s\\n" "$1" >> "$SOLAR_WORKSPACE/sent.log"\n')
    task = task_file(root, 'completed', '')
    seed(root)
    run_env = env_for(root, {**env, 'TMPDIR': str(tmp_path), 'SOLAR_NOTIFY_LOCK_WAIT': '10'})
    cmd = ['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)]
    first = subprocess.Popen(cmd, env=run_env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 15
        while not started_marker.exists():             # wait until the first notifier is inside its slow sender
            assert time.time() < deadline, 'the first notifier never reached its sender'
            time.sleep(0.2)
        os.kill(first.pid, signal.SIGKILL)             # dies by signal, its slow sender still running
        first.wait(timeout=5)
        slow.unlink()
        started = time.time()
        second = subprocess.run(cmd, env=run_env, text=True, capture_output=True, timeout=20)
        assert second.returncode == 0, second.stderr
        assert time.time() - started < 8, 'the dead notifier\'s sender kept the lock'
        assert (workspace / 'sent.log').read_text().count('Task completed') == 1
    finally:
        try:
            os.killpg(first.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_a_python_without_fcntl_is_reported_as_an_unavailable_lock_not_a_timeout(tmp_path):
    import shutil
    import time
    workspace, root, env = fixture_env(tmp_path)
    shim = tmp_path / 'bin'
    shim.mkdir()
    (shim / 'python3').write_text('#!/bin/bash\nif [[ "$*" == *"import fcntl"* ]]; then exit 1; fi\n'
                                  f'exec {shutil.which("python3")} "$@"\n')
    (shim / 'python3').chmod(0o755)
    task = task_file(root, 'completed', '')
    seed(root)
    started = time.time()
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=env_for(root, {**env, 'PATH': f"{shim}:{env['PATH']}"}),
                            text=True, capture_output=True, timeout=30)
    mirror(root)
    assert result.returncode == 1 and 'notify_lock_unavailable' in result.stderr
    assert time.time() - started < 20, 'it waited out the whole lock wait'
    assert 'notify_error: notify_lock_unavailable' in task.read_text()
    assert not (workspace / 'sent.log').exists()


def _requeue(task):
    """The error -> queued move requeue_from_error.sh makes: same run, no new claim."""
    import solar_state
    with solar_state.session() as store:
        store.task_transition(task_id_of(task), 'queued')


def test_a_failure_requeued_while_the_notice_waits_is_not_announced_as_a_completion(tmp_path):
    import time
    workspace, root, env, task = _notify_when(tmp_path, 'error', 'completed,failed', 'notify_run: run-1\n')
    seed(root)
    holder = _hold_lock(tmp_path, task, 30)
    try:
        proc = subprocess.Popen(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                                env=env_for(root, {**env, 'TMPDIR': str(tmp_path), 'SOLAR_NOTIFY_LOCK_WAIT': '20',
                                                   'SOLAR_NOTIFY_EXPECT_RUN': 'run-1',
                                                   'SOLAR_NOTIFY_EXPECT_STATUS': 'error'}),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        _requeue(task)
        holder.kill()
        proc.communicate(timeout=30)
        assert proc.returncode == 0
        assert not (workspace / 'sent.log').exists(), 'a requeued failure was announced'
    finally:
        holder.kill()


def test_a_failure_requeued_after_the_notice_was_built_is_not_sent(tmp_path):
    """The task moves right after the notifier's one read: the last look before sending must catch it."""
    import shutil
    workspace, root, env, task = _notify_when(tmp_path, 'error', 'completed,failed', 'notify_run: run-1\n')
    seed(root)
    shim = tmp_path / 'bin'
    shim.mkdir()
    counter = tmp_path / 'snapshots'
    real = shutil.which('python3')
    (shim / 'python3').write_text(
        '#!/bin/bash\n'
        'if [[ "$1" == *solar_state.py && "$2" == task && "$3" == snapshot ]]; then\n'
        f'  "{real}" "$@"; rc=$?\n'
        f'  n=$(cat "{counter}" 2>/dev/null || echo 0); echo $((n + 1)) > "{counter}"\n'
        f'  if [[ $n == 0 ]]; then "{real}" "$1" task transition "{task_id_of(task)}" queued >/dev/null; fi\n'
        '  exit $rc\n'
        'fi\n'
        f'exec "{real}" "$@"\n')
    (shim / 'python3').chmod(0o755)
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=env_for(root, {**env, 'PATH': f"{shim}:{env['PATH']}", 'SOLAR_NOTIFY_EXPECT_RUN': 'run-1',
                                               'SOLAR_NOTIFY_EXPECT_STATUS': 'error'}),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert counter.exists() and int(counter.read_text()) >= 2, 'the script did not take a last look'
    assert not (workspace / 'sent.log').exists(), 'a failure moved after the snapshot reached the chat'


def test_the_worker_failure_path_stores_the_code_the_notice_reads(tmp_path, monkeypatch):
    import solar_state
    sys_path = str(SCRIPTS)
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import execute_active as ea
    workspace, root, env, task = _notify_when(tmp_path, 'queued', 'failed')
    seed(root)
    with solar_state.session() as store:
        claim = store.task_claim_detail(task_id_of(task), 'worker')
    monkeypatch.setenv('SOLAR_TASK_TOKEN', claim['token'])
    ea.mark_task_error(str(task), task_id_of(task), 'Delivery', 'claude', 'provider_quota', 'quota exceeded with sk-1',
                       tmp_path / 'worker.log')
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=env_for(root, env), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    sent = (workspace / 'sent.log').read_text()
    assert 'Reason: provider_quota' in sent and 'sk-1' not in sent


def test_a_snapshot_that_cannot_be_read_leaves_a_trace_instead_of_a_silent_exit(tmp_path):
    import shutil
    workspace, root, env = fixture_env(tmp_path)
    task = task_file(root, 'completed', '')
    seed(root)
    shim = tmp_path / 'bin'
    shim.mkdir()
    real = shutil.which('python3')
    (shim / 'python3').write_text(
        '#!/bin/bash\n'
        'if [[ "$1" == *solar_state.py && "$2" == task && "$3" == snapshot ]]; then exit 1; fi\n'
        f'exec "{real}" "$@"\n')
    (shim / 'python3').chmod(0o755)
    result = subprocess.run(['bash', str(SCRIPTS / 'notify_if_configured.sh'), task_id_of(task)],
                            env=env_for(root, {**env, 'PATH': f"{shim}:{env['PATH']}"}),
                            text=True, capture_output=True, timeout=30)
    mirror(root)
    assert result.returncode == 1 and 'notify_snapshot_failed' in result.stderr
    assert 'notify_error: notify_snapshot_failed' in task.read_text()
    assert not (workspace / 'sent.log').exists()


def test_the_cleanup_failure_path_announces_the_run_it_failed(tmp_path):
    """complete.sh fails a task on a cleanup error: `state task fail` now says which run, for the notice."""
    import json
    workspace, root, env, task = _notify_when(tmp_path, 'active', 'failed', 'notify_run: run-1\n')
    seed(root)
    import solar_state
    with solar_state.session() as store:
        pass
    out = subprocess.run(['python3', str(SCRIPTS.parents[1] / 'solar-state/scripts/solar_state.py'),
                          'task', 'fail', task_id_of(task), '--field', 'cleanup_error=true'],
                         env=env_for(root, env), text=True, capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)['run'], out.stdout
