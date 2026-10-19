"""Help discovery must bind capabilities to declarations, never incidental text."""
import os
import subprocess

import pytest
from cli_capabilities import advertised_values, discover, option_blocks
from execution_profiles import ProfileError


@pytest.mark.parametrize('text', [
    'Options:\n  --mode <mode>  Modes: ask (read-only), plan\n',
    'Flags:\n    -m, --mode=MODE  Choose a mode\n        Values: plan, ask\n',
    'Options:\n\t--mode <mode>\n\t  Values: ask, plan\n',
    'Options:\n  --mode [ask|plan]  Choose\n',
])
def test_help_redaction_order_and_wrapping_do_not_change_capabilities(text):
    assert 'ask' in advertised_values(option_blocks(text)['--mode'])


@pytest.mark.parametrize('text', [
    'Example: cli --mode ask',
    '  --model <name>  Example: --mode ask',
    'Options:\n  --mode-extra ask',
    'Options:\n  --mode <name>  plan\nExamples:\n  cli --mode ask',
    'Options:\n  --mode <name>  plan\nExamples:\n  --mode ask',
    'Examples:\n  --mode ask\n\nOptions:\n  --mode <mode>  Modes: write, plan\n',
    'Usage:\n  --mode ask\nOptions:\n  --mode <mode>  Modes: write, plan\n',
    'Options:\n  --mode <mode>  Supported values: write. The ask mode was removed.\n',
    'Options:\n  --mode <mode>  e.g. --mode ask\n',
    'Options:\n  --model <m>  Pick a model\n               --mode ask\n',
    'Options:\n  --mode <m>  Values: write. Not one of ask, plan.\n',
    'Options:\n  --mode <m>  Mode (see docs) [write|edit] Not like (ask, plan)\n',
    'Options:\n  --mode <m>  Format: ask\n',
])
def test_incidental_text_never_proves_an_option_or_its_value(text):
    assert 'ask' not in advertised_values(option_blocks(text).get('--mode', ''))


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


def test_a_failing_version_command_never_records_its_label(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        if '--version' in argv: return subprocess.CompletedProcess(argv, 1, 'valid-label', '')
        return subprocess.CompletedProcess(argv, 0, '  --print  Print\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    metadata = {}
    discover('synthetic', dict(os.environ), str(tmp_path), provider='agent', prefix=[],
             required=['--print'], values={}, metadata=metadata)
    assert metadata['version'] is None


@pytest.mark.parametrize('text', [
    'Examples:\n  --mode ask\n  --print\n',
    'Options:\n  --model <m>  Pick one\n               --print  nested in the description\n',
])
def test_examples_and_nested_text_never_declare_an_option(text):
    assert '--print' not in option_blocks(text)


def test_coloured_help_is_parsed_and_asked_not_to_colour(tmp_path, monkeypatch):
    seen = []
    def run(argv, **kwargs):
        seen.append(kwargs['env'])
        out = '' if '--version' in argv else '\x1b[1mOptions:\x1b[0m\n  \x1b[32m--mode\x1b[0m <m>  Modes: ask, plan\n'
        return subprocess.CompletedProcess(argv, 0, out, '')
    monkeypatch.setattr(subprocess, 'run', run)
    discover('synthetic', dict(os.environ), str(tmp_path), provider='agent', prefix=[],
             required=['--mode'], values={'--mode': 'ask'}, metadata={})
    assert all(e['NO_COLOR'] == '1' and e['TERM'] == 'dumb' and e['CLICOLOR'] == '0' for e in seen)


def test_a_repeated_declaration_never_replaces_the_first_one():
    text = 'Options:\n  --mode <m>  Modes: write\nMore:\n  --mode <m>  Modes: ask\n'
    assert advertised_values(option_blocks(text)['--mode']) == {'write'}


@pytest.mark.parametrize('text', [
    'Options:\n  -p, --print  Print\n      --mode  Mode [choices: "ask", "plan"]\n',
    'Options:\n  --mode <m>  Pick (choices: "plan", "ask")\n',
    'Options:\n  --mode <m>  Pick\n              (choices: "plan", "ask")\n',
    'Options:\n  --mode <f>  Output format (only works with --print): "plan" | "ask" (default: "plan")\n',
    'Options:\n  --mode <m>\n          Possible values:\n          - ask:  read only\n          - plan: plans\n',
])
def test_common_help_layouts_are_recognised(text):
    blocks = option_blocks(text)
    assert '--mode' in blocks and advertised_values(blocks['--mode']) >= {'ask', 'plan'}


def test_an_option_after_a_wider_declaration_is_not_mistaken_for_a_value_source():
    text = 'Options:\n  --mode  Mode\n      --other  Values: ask\n'
    assert advertised_values(option_blocks(text)['--mode']) == set()


def test_an_optional_value_declaration_is_indexed():
    assert '--sandbox' in option_blocks('Options:\n  --sandbox[=<mode>]  Values: enabled\n')


@pytest.mark.parametrize('failure', ['timeout', 'oserror'])
def test_a_version_command_that_hangs_or_is_missing_never_blocks(tmp_path, monkeypatch, failure):
    def run(argv, **kwargs):
        if '--version' in argv:
            raise subprocess.TimeoutExpired(argv, 15) if failure == 'timeout' else OSError('x')
        return subprocess.CompletedProcess(argv, 0, '  --print  Print\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    metadata = {}
    discover('synthetic', dict(os.environ), str(tmp_path), provider='agent', prefix=[],
             required=['--print'], values={}, metadata=metadata)
    assert metadata['version'] is None and metadata['capabilities_checked'] == ['--print']
