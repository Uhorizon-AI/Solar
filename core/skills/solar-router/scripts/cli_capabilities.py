"""No-inference CLI discovery. Versions are diagnostic, never admission policy."""
from __future__ import annotations

import re
import subprocess

from execution_profiles import ProfileError


def unsupported(provider, stage, reason, *, option=None):
    detail = dict(provider=provider, stage=stage, reason=reason)
    if option is not None:
        detail['option'] = option
    return ProfileError('execution_profile_unsupported', detail=detail)


def option_blocks(help_text):
    """Index advertised option declarations, excluding examples and substring hits.

    Values may be described on indented continuation lines. Unknown layouts fail
    closed; neither an example nor another option's description proves support.
    """
    blocks = {}
    current = None
    indent = 0
    for line in help_text.splitlines():
        match = re.match(r'^(\s*)(?:-[A-Za-z?],?\s+)?(--[A-Za-z][\w-]*)(?=[\s=,]|$)(.*)$', line)
        if match:
            indent = len(match[1])
            current = match[2]
            blocks[current] = match[3]
        elif current and line.strip() and len(line) - len(line.lstrip()) > indent:
            blocks[current] += '\n' + line.strip()
        elif line.strip():
            current = None
    return blocks


def discover(binary, env, cwd, *, provider, prefix, required, values, metadata):
    """Check only no-inference CLI commands inside the caller's tested guard."""
    metadata.update(provider=provider, version=None)
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
        if not re.search(r'(?<![\w-])' + re.escape(value) + r'(?![\w-])', blocks.get(option, '')):
            raise unsupported(provider, 'help', 'required_value_unadvertised', option=option)
    metadata['capabilities_checked'] = list(required)
