"""Help discovery must bind capabilities to declarations, never incidental text."""
import os
import subprocess

import pytest
from cli_capabilities import discover, option_blocks
from execution_profiles import ProfileError


@pytest.mark.parametrize('text', [
    'Options:\n  --mode <mode>  Modes: ask (read-only), plan\n',
    'Flags:\n    -m, --mode=MODE  Choose a mode\n        Values: plan, ask\n',
    'Options:\n\t--mode <mode>\n\t  Select ask or plan\n',
])
def test_help_redaction_order_and_wrapping_do_not_change_capabilities(text):
    assert 'ask' in option_blocks(text)['--mode']


@pytest.mark.parametrize('text', [
    'Example: cli --mode ask',
    '  --model <name>  Example: --mode ask',
    'Options:\n  --mode-extra ask',
    'Options:\n  --mode <name>  plan\nExamples:\n  cli --mode ask',
])
def test_incidental_text_never_proves_an_option_or_its_value(text):
    assert 'ask' not in option_blocks(text).get('--mode', '')


REASONS = dict(missing='required_option_missing', renamed='required_option_missing',
               value='required_value_unadvertised', other_option='required_value_unadvertised',
               exit='help_failed', timeout='help_timeout', unavailable='help_unavailable',
               unknown_format='help_format_unknown')


@pytest.mark.parametrize('failure', sorted(REASONS))
def test_unknown_or_changed_help_is_rejected_with_safe_specific_detail(tmp_path, monkeypatch, failure):
    text = '  --mode <mode>  ask\n  --print  Print output\n'
    if failure == 'missing': text = '  --mode <mode>  ask'
    if failure == 'renamed': text = text.replace('--print', '--output')
    if failure == 'value': text = text.replace('ask', 'write')
    if failure == 'other_option': text = '  --mode <mode>  write\n  --print  ask'
    if failure == 'unknown_format': text = 'Usage: cli [thing]\nNo declarations here.'
    def run(argv, **kwargs):
        if '--version' in argv: return subprocess.CompletedProcess(argv, 0, 'new-release', '')
        if failure == 'timeout': raise subprocess.TimeoutExpired(argv, 15)
        if failure == 'unavailable': raise OSError('gone')
        return subprocess.CompletedProcess(argv, 1 if failure == 'exit' else 0, text, 'sensitive diagnostic')
    monkeypatch.setattr(subprocess, 'run', run)
    metadata = {}
    with pytest.raises(ProfileError) as error:
        discover('synthetic', dict(os.environ), str(tmp_path), provider='agent', prefix=[],
                 required=['--print', '--mode'], values={'--mode': 'ask'}, metadata=metadata)
    assert error.value.code == 'execution_profile_unsupported'
    assert error.value.detail['stage'] == 'help'
    assert error.value.detail['reason'] == REASONS[failure]
    assert 'sensitive' not in str(error.value.detail)
    assert metadata['version'] == 'new-release'


@pytest.mark.parametrize('label', ['x' * 200, 'bad\nline', '$(touch x)'])
def test_a_malformed_version_label_is_dropped_not_recorded(tmp_path, monkeypatch, label):
    def run(argv, **kwargs):
        out = label if '--version' in argv else '  --print  Print\n'
        return subprocess.CompletedProcess(argv, 0, out, '')
    monkeypatch.setattr(subprocess, 'run', run)
    metadata = {}
    discover('synthetic', dict(os.environ), str(tmp_path), provider='agent', prefix=[],
             required=['--print'], values={}, metadata=metadata)
    assert metadata['version'] is None
