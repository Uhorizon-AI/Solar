"""The effective admin policy: local sources are read, server-managed policy comes from `claude doctor`."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

import execution_profiles as profiles
from claude_help import claude_help

NO_POLICY = ("Claude Code doctor\n\nManaged settings (remote): not fetched — requires an Enterprise or Team "
             "subscription\nOrganization policy: not applicable to Pro and Max accounts\n")


TEAM = ("Claude Code doctor\n\nManaged settings (remote): checking… (fetch in progress; re-run in a moment)\n"
        "Organization policy: Loaded from api.anthropic.com\n")


def fake_claude(tmp_path, doctor_out=NO_POLICY, doctor_code=0, doctor_sleep=0):
    binary = tmp_path / 'claude-double'
    binary.write_text(f'''#!{sys.executable}
import sys, time
if '--help' in sys.argv:
    print({claude_help()!r})
elif 'doctor' in sys.argv:
    time.sleep({doctor_sleep})
    sys.stdout.write({doctor_out!r})
    sys.exit({doctor_code})
''')
    binary.chmod(0o700)
    return str(binary)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine with no admin policy anywhere; the roots and the HOME are temporary directories."""
    root = tmp_path / 'managed'
    root.mkdir()
    (tmp_path / 'home' / '.claude').mkdir(parents=True)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(profiles, 'MANAGED_ROOTS', (str(root),))
    monkeypatch.setattr(profiles, 'MANAGED_PREFERENCES', ())
    return root


def effective(binary, tmp_path):
    return profiles._effective_managed_policy(binary, dict(os.environ), str(tmp_path))


def test_no_local_source_and_no_organization_policy_is_known_empty(machine, tmp_path):
    assert effective(fake_claude(tmp_path), tmp_path) == {}


def test_an_empty_managed_settings_object_is_still_empty(machine, tmp_path):
    (machine / 'managed-settings.json').write_text('{}')
    assert effective(fake_claude(tmp_path), tmp_path) == {}


@pytest.mark.parametrize('name,body', [
    ('managed-settings.json', {'permissions': {'defaultMode': 'bypassPermissions'}}),
    ('managed-settings.d/10-hooks.json', {'hooks': {'SessionStart': 'x'}}),
])
def test_a_present_local_policy_is_returned_and_never_ignored(machine, tmp_path, name, body):
    path = machine / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(body))
    # the doctor is not even consulted: the binary below does not exist
    assert effective(str(tmp_path / 'missing'), tmp_path) == body


def test_hidden_and_non_json_dropins_are_ignored_like_the_cli_does(machine, tmp_path):
    dropins = machine / 'managed-settings.d'
    dropins.mkdir()
    (dropins / '.hidden.json').write_text('{"hooks": {}}')
    (dropins / 'notes.txt').write_text('not policy')
    assert effective(fake_claude(tmp_path), tmp_path) == {}


def test_a_managed_mcp_file_counts_as_policy(machine, tmp_path):
    (machine / 'managed-mcp.json').write_text('{}')
    assert effective(fake_claude(tmp_path), tmp_path) == {'managed-mcp.json': True}


def test_a_managed_preferences_plist_counts_as_policy(machine, tmp_path, monkeypatch):
    plist = tmp_path / 'com.anthropic.claudecode.plist'
    plist.write_text('plist')
    monkeypatch.setattr(profiles, 'MANAGED_PREFERENCES', (str(plist),))
    assert effective(fake_claude(tmp_path), tmp_path) == {'mdm': True}


@pytest.mark.parametrize('content', ['{not json', '[]', '"text"'])
def test_an_unreadable_or_non_object_source_is_unknown(machine, tmp_path, content):
    (machine / 'managed-settings.json').write_text(content)
    assert effective(fake_claude(tmp_path), tmp_path) is None


@pytest.mark.parametrize('out,code', [
    ('Managed settings (remote): loaded from claude.ai\nOrganization policy: loaded from remote\n', 0),
    ('Organization policy: not applicable to Pro and Max accounts\n', 0),     # the remote line is missing
    ('Managed settings (remote): not fetched — requires an Enterprise or Team subscription\n', 0),
    ('', 0),
    (NO_POLICY, 1),
])
def test_any_other_doctor_answer_is_unknown(machine, tmp_path, out, code):
    assert effective(fake_claude(tmp_path, doctor_out=out, doctor_code=code), tmp_path) is None


def remote_cache(tmp_path, body='{}', age=60, synced=True):
    """The CLI's cache of server-managed settings under the temporary HOME."""
    cache = tmp_path / 'home' / '.claude' / 'remote-settings.json'
    cache.write_text(body)
    stamp = Path(str(cache) + '.synced-at')
    if synced:
        stamp.write_text(str(int((time.time() - age) * 1000)))
    return cache


def test_a_team_account_with_a_fresh_empty_managed_settings_cache_is_known_empty(machine, tmp_path):
    remote_cache(tmp_path)
    assert effective(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) == {}


@pytest.mark.parametrize('kwargs,reason', [
    (dict(body='{"hooks": {"SessionStart": "x"}}'), 'remote_policy_present'),
    (dict(age=2 * profiles.REMOTE_SETTINGS_MAX_AGE), 'remote_policy_cache_stale'),
    (dict(age=-3600), 'remote_policy_cache_stale'),                        # a stamp from the future
    (dict(synced=False), 'remote_policy_cache_unreadable'),
    (dict(body='{not json'), 'remote_policy_cache_unreadable'),
    (dict(body='[]'), 'remote_policy_cache_unreadable'),
])
def test_a_team_account_without_proof_of_an_empty_cache_is_unknown_with_a_reason(machine, tmp_path, kwargs, reason):
    remote_cache(tmp_path, **kwargs)
    binary = fake_claude(tmp_path, doctor_out=TEAM)
    assert effective(binary, tmp_path) is None
    why = []
    profiles._effective_managed_policy(binary, dict(os.environ), str(tmp_path), why)
    assert why == [reason]


def test_a_team_account_with_no_cache_at_all_is_unknown(machine, tmp_path):
    assert effective(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) is None


def test_the_cache_alone_is_not_enough_without_the_team_wording(machine, tmp_path):
    remote_cache(tmp_path)
    other = TEAM.replace('Loaded from api.anthropic.com', 'Loaded from somewhere else')
    assert effective(fake_claude(tmp_path, doctor_out=other), tmp_path) is None
    done = TEAM.replace('checking… (fetch in progress; re-run in a moment)', 'loaded from claude.ai')
    assert effective(fake_claude(tmp_path, doctor_out=done), tmp_path) is None


def test_a_local_policy_still_wins_over_a_clean_cache(machine, tmp_path):
    remote_cache(tmp_path)
    (machine / 'managed-settings.json').write_text('{"hooks": {"SessionStart": "x"}}')
    assert effective(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) == {'hooks': {'SessionStart': 'x'}}


def test_preflight_passes_a_team_account_with_an_empty_cache_and_fails_with_a_policy(machine, tmp_path):
    binary = fake_claude(tmp_path, doctor_out=TEAM)
    cache = remote_cache(tmp_path)
    profiles.preflight(binary, dict(os.environ), str(tmp_path))          # no exception
    cache.write_text('{"permissions": {"defaultMode": "bypassPermissions"}}')
    with pytest.raises(profiles.ProfileError) as caught:
        profiles.preflight(binary, dict(os.environ), str(tmp_path))
    assert caught.value.detail == dict(provider='claude', stage='policy', reason='remote_policy_present')


def test_a_doctor_that_does_not_answer_in_time_is_unknown(machine, tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, 'DOCTOR_TIMEOUT', 0.5)
    assert effective(fake_claude(tmp_path, doctor_sleep=5), tmp_path) is None


def test_a_missing_cli_is_unknown(machine, tmp_path):
    assert effective(str(tmp_path / 'missing'), tmp_path) is None


def test_preflight_passes_on_a_machine_without_policy_and_fails_with_one(machine, tmp_path):
    binary = fake_claude(tmp_path)
    profiles.preflight(binary, dict(os.environ), str(tmp_path))          # no exception
    (machine / 'managed-settings.json').write_text('{"hooks": {"SessionStart": "x"}}')
    with pytest.raises(profiles.ProfileError, match='execution_profile_unsupported'):
        profiles.preflight(binary, dict(os.environ), str(tmp_path))


@pytest.mark.skipif(not os.environ.get('SOLAR_TEST_REAL_CLAUDE'),
                    reason='opt-in: needs the real claude CLI, logged in under the real HOME, on a machine without admin policy')
def test_the_real_cli_on_a_machine_without_policy_is_known_empty(tmp_path):
    binary = Path(os.environ.get('SOLAR_TEST_REAL_CLAUDE_BIN') or 'claude')
    env = {k: v for k, v in os.environ.items() if k in profiles.ENV_ALLOWLIST}
    resolved = str(binary) if binary.is_absolute() else __import__('shutil').which(str(binary))
    assert resolved, 'claude is not on PATH'
    profiles.preflight(resolved, env, str(tmp_path))
