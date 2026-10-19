"""No-inference CLI discovery. Versions are diagnostic, never admission policy."""
from __future__ import annotations

import re
import subprocess

from execution_profiles import ProfileError

_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
_SECTION = re.compile(r'^\S[^\n]*:\s*$')
_SKIPPED = re.compile(r'example|usage', re.I)
_OPTION = re.compile(r'^(\s*)(?:-[A-Za-z?],?\s+)?(--[A-Za-z][\w-]*)(?=[\s=,]|$)(.*)$')
_LABEL = re.compile(r'(?<![\w<-])(?:(?:values?|modes?|formats?|choices)\s*:|one of\b)\s*(.+?)(?:\.(?:\s|$)|$)', re.I | re.M)
_GROUP = re.compile(r'[\[<{(]([\w.-]+(?:\s*[|,]\s*[\w.-]+)+)[\]>})]')


def unsupported(provider, stage, reason, *, option=None):
    detail = dict(provider=provider, stage=stage, reason=reason)
    if option is not None:
        detail['option'] = option
    return ProfileError('execution_profile_unsupported', detail=detail)


def option_blocks(help_text):
    """Index advertised option declarations, excluding examples and substring hits.

    Colour codes are removed. Lines under an `Examples:`/`Usage:` header are never
    declarations, and an option-looking line indented under another option is part
    of that option's description. The first declaration wins. Only the first option
    of a line is indexed, so aliases or `--x[=V]` layouts are rejected rather than
    guessed. Unknown layouts fail closed.
    """
    blocks = {}
    current = None
    indent = 0
    skipping = False
    for line in _ANSI.sub('', help_text).splitlines():
        if _SECTION.match(line) and not _OPTION.match(line):
            skipping = bool(_SKIPPED.search(line))
            current = None
            continue
        if skipping:
            continue
        match = _OPTION.match(line)
        nested = bool(match and current and len(match[1]) > indent)
        if match and not nested:
            if match[2] in blocks:
                current = None
            else:
                indent = len(match[1])
                current = match[2]
                blocks[current] = match[3]
        elif current and line.strip() and len(line) - len(line.lstrip()) > indent:
            blocks[current] += '\n' + line.strip()
        elif line.strip():
            current = None
    return blocks


def advertised_values(block):
    """Values an option block lists in a recognised form (`Values: a, b`, `[a|b]`).

    A word that merely appears in prose never counts as a supported value.
    """
    found = set()
    parts = [m[1] for m in _LABEL.finditer(block)] + [m[1] for m in _GROUP.finditer(block)]
    for part in parts:
        part = re.sub(r'\([^)]*\)', ' ', part)
        for token in re.split(r'[,|/]|\bor\b', part):
            token = token.strip(' \t`"\'[]<>{}')
            if re.fullmatch(r'[\w.-]+', token):
                found.add(token)
    return found


def discover(binary, env, cwd, *, provider, prefix, required, values, metadata):
    """Check only no-inference CLI commands inside the caller's tested guard."""
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
        result = subprocess.run([*prefix, binary, '--help'], cwd=cwd, env=env,
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
