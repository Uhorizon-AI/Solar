"""Help discovery must bind capabilities to declarations, never incidental text."""
import os
import subprocess
from pathlib import Path

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
    'Options:\n  --mode <m>  Pick (choices: plan, ask)\n',
    'Options:\n  --mode <m>  Pick\n              (choices: "plan", "ask")\n',
    'Options:\n  --mode <f>  Output format (only works with --print): "plan" | "ask" (default: "plan")\n',
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


def test_an_indented_examples_header_hides_what_follows_it():
    text = 'Options:\n --mode <mode> Modes: ask, plan\n Examples:\n --print\n'
    assert sorted(option_blocks(text)) == ['--mode']


def test_a_title_such_as_usage_of_is_not_an_examples_section():
    text = 'Usage of tool:\n  --print   Print\n  --mode   Set the mode (accept-edits, plan)\nExamples:\n  --extra\n'
    blocks = option_blocks(text)
    assert sorted(blocks) == ['--mode', '--print'] and advertised_values(blocks['--mode']) == {'accept-edits', 'plan'}


def test_a_parenthesised_note_is_not_a_value_list_unless_it_closes_the_description():
    assert advertised_values(' <m>  Pick one (e.g., ask)') == set()
    assert advertised_values(' <m>  Pick one (for example, ask) and more') == set()


def test_an_examples_section_ends_at_a_header_of_the_same_or_shallower_indent_only():
    deeper = 'Options:\n  Examples:\n    Note:\n    --print\n'
    assert '--print' not in option_blocks(deeper)
    same = 'Options:\n  Examples:\n    --a\n  More:\n  --b  x\n'
    assert sorted(option_blocks(same)) == ['--b']


@pytest.mark.parametrize('text', [
    ' <m>  Modes: plan (ask, plan)',
    ' <m>  (choices: "plan") ask is deprecated (ask, legacy)',
    ' <m>  Removed [ask|plan] in 2.0; modes: write',
    ' <m>  Values: none of ask, plan',
    ' <m>  Values: not one of ask, plan',
    ' <m>  Values: not one of "ask", "plan"',
    ' <m>  Values: none of "ask", "plan"',
    ' <m>  Removed "ask" | "plan" in 2.0',
])
def test_withdrawn_or_secondary_lists_never_prove_a_value(text):
    assert 'ask' not in advertised_values(text)


@pytest.mark.parametrize('text,expected', [
    (' <m>  {a,b} or {c}', {'a', 'b'}),  # an unknown layout fails closed, never guessed
    (' <m>  Values: write. May be one of ask, plan.', {'write', 'ask', 'plan'}),
    (' <m>  (choices: "plan") ask is deprecated (ask, legacy)', {'plan'}),
])
def test_chained_groups_and_later_sentences_are_read_whole(text, expected):
    assert advertised_values(text) == expected


def test_a_closing_note_is_ignored_when_a_list_exists_a_documented_trade_off():
    assert advertised_values(' <m>  Modes: read. Defaults (read, write)') == {'read'}
    assert advertised_values(' <m>  Set (accept-edits, plan)') == {'accept-edits', 'plan'}


def test_an_example_line_inside_an_option_description_does_not_drop_later_options():
    """Claude CLI 2.1.314 puts `Example:` on its own line inside the description of
    `--json-schema` (captured from the real `claude --help` of that version); #104."""
    text = (Path(__file__).parent / 'fixtures' / 'claude_2.1.314_help.txt').read_text()
    blocks = option_blocks(text)
    for option in ('--json-schema', '--max-budget-usd', '--mcp-config', '--model',
                   '--no-session-persistence', '--output-format'):
        assert option in blocks, option
    assert '"type":"object"' in blocks['--json-schema']


def test_an_examples_section_is_never_read_as_declarations_even_when_indented_deeper():
    """Review of #104: only a singular `Example:` at the description column belongs to an option."""
    text = '\n'.join(['  --model <m>', '    Examples:', '      --print', '', 'Other:', '  --effort <e>   Level'])
    blocks = option_blocks(text)
    assert '--model' in blocks
    assert '--print' not in blocks
    assert '--effort' in blocks


def test_an_example_inside_an_option_whose_description_starts_on_the_next_line_keeps_the_following_options():
    """Review of #104: no two-space gap on the option line leaves no description column."""
    text = '\n'.join(['  --allowedTools, --allowed-tools <tools...>', '      Tools to allow.', '      Example: Bash(git:*)',
                      '  --effort <e>   Level'])
    blocks = option_blocks(text)
    assert '--allowedTools' in blocks
    assert '--effort' in blocks
