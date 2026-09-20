"""send_telegram.sh parse modes, with curl replaced by a stub that records its arguments."""
import os
import subprocess
from pathlib import Path

import pytest

SEND = Path(__file__).resolve().parents[3] / 'skills/solar-telegram/scripts/send_telegram.sh'


def run_send(tmp_path, parse_mode):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    curl = bin_dir / 'curl'
    curl.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$CURL_ARGS"\necho \'{"ok":true}\'\n')
    curl.chmod(0o755)
    args_file = tmp_path / 'curl_args'
    env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'CURL_ARGS': str(args_file),
           'TELEGRAM_BOT_TOKEN': 'fake', 'TELEGRAM_CHAT_ID': '456'}
    env.pop('TELEGRAM_PARSE_MODE', None)
    if parse_mode is not None:
        env['TELEGRAM_PARSE_MODE'] = parse_mode
    result = subprocess.run(['bash', str(SEND), 'Task completed: a_b'], cwd=tmp_path, env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    return args_file.read_text().splitlines()


@pytest.mark.parametrize('mode', ['none', 'NONE'])
def test_none_sends_plain_text(tmp_path, mode):
    args = run_send(tmp_path, mode)
    assert not any(a.startswith('parse_mode=') for a in args)
    assert 'text=Task completed: a_b' in args


@pytest.mark.parametrize('mode,expected', [(None, 'Markdown'), ('HTML', 'HTML')])
def test_other_modes_keep_parse_mode(tmp_path, mode, expected):
    args = run_send(tmp_path, mode)
    assert f'parse_mode={expected}' in args
