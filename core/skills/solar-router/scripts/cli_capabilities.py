"""No-inference CLI discovery. Versions are diagnostic, never admission policy."""
from __future__ import annotations

import re
import subprocess

from execution_profiles import ProfileError

_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
_HEADER = re.compile(r'^(\s*)\S[^\n]*:\s*$')
_SKIPPED = re.compile(r'^\s*(?:examples?|usage)\s*:\s*$', re.I)
_EXAMPLE = re.compile(r'^\s*example\s*:\s*$', re.I)
_OPTION = re.compile(r'^(\s*)(?:-[A-Za-z?],?\s+)?(--[A-Za-z][\w-]*)(?=[\s=,\[]|$)(.*)$')
# A label counts only where a description or sentence begins, or inside brackets.
_START = r'(?:^|(?<=[.;(\[)\]>])\s*|(?<=\s\s))'
_LABEL = re.compile(_START + r'(?:(?:(?:possible|supported|allowed|valid)\s+)?values|modes|choices|formats|output\s+formats?(?:\s*\([^)]*\))?)\s*:'
                    r'\s*(.+?)(?:\.(?:\s|$)|$)', re.I | re.M)
_ONE_OF = re.compile(_START + r'(?:(?:must|can|may)\s+be\s+)?one\s+of\s+(.+?)(?:\.(?:\s|$)|$)', re.I | re.M)
_GROUP = re.compile(r'[\[<{]([\w.-]+(?:\s*[|,]\s*[\w.-]+)+)[\]>}]')
# A parenthesised list counts only as the closing note of a description, never
# prose such as "(e.g., ask)".
_PAREN = re.compile(r'(?<!like )(?<!not )(?<!unlike )(?<!except )(?<!without )\(([a-z0-9][\w-]*(?:\s*[|,]\s*[a-z0-9][\w-]*)+)\)(?=\s*(?:\(default|\.|$))', re.I)
_QUOTED = re.compile(r'"[\w.-]+"(?:\s*[|,]\s*"[\w.-]+")+')


def unsupported(provider, stage, reason, *, option=None):
    detail = dict(provider=provider, stage=stage, reason=reason)
    if option is not None:
        detail['option'] = option
    return ProfileError('execution_profile_unsupported', detail=detail)


def option_blocks(help_text):
    """Index advertised option declarations, excluding examples and substring hits.

    Colour codes are removed. Lines under an `Examples:`/`Usage:` header (any
    indentation) are never declarations until the next header at the same or a
    shallower indent, except a singular `Example:` at the description column of
    the current option, which is part of that option's description; a title such as `Usage of agy:` is not such a header, and an option-looking line indented to the description column of
    another option is part of that option's description. The first declaration wins. Only the first option
    of a line is indexed, so aliases or `--x[=V]` layouts are rejected rather than
    guessed. Unknown layouts fail closed.
    """
    blocks = {}
    current = None
    indent = 0
    column = None
    skip_indent = None
    for line in _ANSI.sub('', help_text).splitlines():
        header = None if _OPTION.match(line) else _HEADER.match(line)
        if skip_indent is not None:
            if not (header and len(header[1]) <= skip_indent and not _SKIPPED.match(line)):
                continue
            skip_indent = None
        # A singular `Example:` at the description column of the option it follows is part of that
        # option's description; any other Example(s)/Usage header starts a skipped section.
        if _SKIPPED.match(line) and not (current and column and _EXAMPLE.match(line)
                                         and len(line) - len(line.lstrip()) >= column):
            skip_indent = len(line) - len(line.lstrip())
            current = None
            continue
        if header and not header[1]:
            current = None
            continue
        match = _OPTION.match(line)
        nested = bool(match and current and column and len(match[1]) >= column)
        if match and not nested:
            if match[2] in blocks:
                current = None
            else:
                indent = len(match[1])
                current = match[2]
                blocks[current] = match[3]
                gap = re.search(r'\S\s{2,}(?=\S)', line[len(match[1]):])
                column = len(match[1]) + gap.end() if gap else None
        elif current and line.strip() and len(line) - len(line.lstrip()) > indent:
            blocks[current] += '\n' + line.strip()
        elif line.strip():
            current = None
    return blocks


_NEGATED = re.compile(r'^\s*(?:none\s+of|not\b|never\b|no\s+longer|removed|deprecated|unlike)', re.I)
_WITHDRAWN = re.compile(r'(?:none\s+of|not\s+one\s+of|removed|deprecated|not|never|unlike|no\s+longer)[\s:]*$', re.I)


def _until_unmatched_paren(text):
    depth = 0
    for index, char in enumerate(text):
        depth += char == '('
        if char == ')':
            if not depth:
                return text[:index]
            depth -= 1
    return text


def advertised_values(block):
    """Values an option block lists in a recognised form (`Values: a, b`, `[a|b]`).

    Recognised, as in the real Cursor and Antigravity help: `Values:`/`Modes:`/
    `Formats:`/`Choices:` (also `Possible values:`, `Output format (...):`), a
    sentence starting `one of`, `[a|b]`/`<a|b>`/`{a,b}` groups, quoted `"a" | "b"`
    lists (including `(choices: "a", "b")`) and, only when nothing else is listed,
    a closing `(a, b)` note. Lists or groups introduced by a negation (`none of`,
    `not one of`, `removed`, ...) are ignored. A word that merely appears in prose
    never counts as a supported value.
    """
    block = re.sub(r'([|,])[ \t]*\n\s*', r'\1 ', block)  # a list wrapped after its separator
    parts = [m[1] for pattern in (_LABEL, _ONE_OF) for m in pattern.finditer(block)]
    for match in _GROUP.finditer(block):
        if not _WITHDRAWN.search(block[:match.start()]):
            parts.append(match[1])
    parts += [m[0] for m in _QUOTED.finditer(block) if not _WITHDRAWN.search(block[:m.start()])]
    if not parts:
        parts = [m[1] for m in _PAREN.finditer(block)]
    found = set()
    for part in parts:
        if _NEGATED.match(part):
            continue
        part = re.sub(r'\([^)]*\)', ' ', _until_unmatched_paren(part))
        for token in re.split(r'[,|/\n]|\bor\b', part):
            token = token.strip(' \t`"\'[]<>{}()')
            if re.fullmatch(r'[\w.-]+', token):
                found.add(token)
    return found


def discover(binary, env, cwd, *, provider, prefix, required, values, metadata, subcommand=()):
    """Check only no-inference CLI commands inside the caller's tested guard.

    `subcommand` names the command whose `--help` declares the options (`exec` for Codex); the
    version is always the binary's own."""
    metadata.update(provider=provider, version=None)
    env = {**env, 'NO_COLOR': '1', 'TERM': 'dumb', 'CLICOLOR': '0'}
    try:
        version = subprocess.run([*prefix, binary, '--version'], cwd=cwd, env=env,
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        label = version.stdout.strip()
        if version.returncode == 0 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._+()/:-]{0,127}', label):
            metadata['version'] = label
    except (OSError, subprocess.SubprocessError, UnicodeError):
        pass  # Version is optional evidence, never a safety capability.
    try:
        result = subprocess.run([*prefix, binary, *subcommand, '--help'], cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise unsupported(provider, 'help', 'help_timeout') from None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise unsupported(provider, 'help', 'help_unavailable') from None
    if result.returncode:
        raise unsupported(provider, 'help', 'help_failed')
    blocks = option_blocks(result.stdout + '\n' + result.stderr)
    if not blocks:
        raise unsupported(provider, 'help', 'help_format_unknown')
    for option in required:
        if option not in blocks:
            raise unsupported(provider, 'help', 'required_option_missing', option=option)
    for option, value in values.items():
        if value not in advertised_values(blocks.get(option, '')):
            raise unsupported(provider, 'help', 'required_value_unadvertised', option=option)
    metadata['capabilities_checked'] = list(required)
