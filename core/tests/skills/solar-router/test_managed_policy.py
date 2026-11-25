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


def fake_claude(tmp_path, doctor_out=NO_POLICY, doctor_code=0, doctor_sleep=0, sync=None, sync_delay=0.0):
    """`sync` is a JSON body: the double then rewrites the CLI's cache of server-managed settings and its
    stamp `sync_delay` seconds after `doctor` returns, as the real CLI's background sync does."""
    cache = Path(os.environ['HOME']) / '.claude' / 'remote-settings.json'
    body = tmp_path / 'sync-body'
    body.write_text(sync or '')
    binary = tmp_path / 'claude-double'
    binary.write_text(f'''#!{sys.executable}
import subprocess, sys, time
if '--help' in sys.argv:
    print({claude_help()!r})
elif 'doctor' in sys.argv:
    time.sleep({doctor_sleep})
    sys.stdout.write({doctor_out!r})
    sys.stdout.flush()
    if {sync!r} is not None:
        subprocess.Popen([sys.executable, '-c', "import time,pathlib; time.sleep({sync_delay}); "
            "p=pathlib.Path({str(cache)!r}); p.write_text(pathlib.Path({str(body)!r}).read_text()); "
            "pathlib.Path(str(p)+'.synced-at').write_text(str(int(time.time()*1000)))"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
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


@pytest.fixture
def fast_sync(monkeypatch):
    monkeypatch.setattr(profiles, 'REMOTE_SETTINGS_SYNC_WAIT', 1.0)
    monkeypatch.setattr(profiles, 'REMOTE_SETTINGS_POLL', 0.05)


def cache_path(tmp_path):
    return tmp_path / 'home' / '.claude' / 'remote-settings.json'


def old_cache(tmp_path, body='{}', age=3600):
    """A cache left by an earlier sync: it does not prove the policy of this check."""
    cache = cache_path(tmp_path)
    cache.write_text(body)
    Path(str(cache) + '.synced-at').write_text(str(int((time.time() - age) * 1000)))
    return cache


def why_of(binary, tmp_path):
    why = []
    result = profiles._effective_managed_policy(binary, dict(os.environ), str(tmp_path), why)
    return result, why


def test_a_team_account_whose_cache_is_synced_during_the_check_and_empty_is_known_empty(machine, tmp_path, fast_sync):
    old_cache(tmp_path, body='{"hooks": {"x": 1}}')           # stale content from an earlier sync is replaced
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM, sync='{}', sync_delay=0.2), tmp_path) == ({}, [])


def test_a_team_account_whose_synced_cache_holds_a_policy_is_refused(machine, tmp_path, fast_sync):
    binary = fake_claude(tmp_path, doctor_out=TEAM, sync='{"hooks": {"SessionStart": "x"}}')
    assert why_of(binary, tmp_path) == (None, ['remote_policy_present'])


@pytest.mark.parametrize('age', [0, 5, 3600, 86400])
def test_a_cache_from_before_the_check_is_never_proof_however_recent(machine, tmp_path, fast_sync, age):
    old_cache(tmp_path, age=age + 1)       # synced before this check started, so no sync happened during it
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) == (None, ['remote_policy_sync_pending'])


def test_a_team_account_with_no_cache_at_all_is_unreadable(machine, tmp_path, fast_sync):
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) == (None, ['remote_policy_cache_unreadable'])


@pytest.mark.parametrize('stamp', ['', 'abc', '1.5', '-3', '1e12', '9' * 400, ' '])
def test_a_stamp_that_is_not_a_plain_integer_is_unreadable(machine, tmp_path, fast_sync, stamp):
    cache_path(tmp_path).write_text('{}')
    Path(str(cache_path(tmp_path)) + '.synced-at').write_text(stamp)
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) == (None, ['remote_policy_cache_unreadable'])


def test_a_stamp_from_the_future_is_not_a_sync(machine, tmp_path, fast_sync):
    cache_path(tmp_path).write_text('{}')
    Path(str(cache_path(tmp_path)) + '.synced-at').write_text(str(int((time.time() + 3600) * 1000)))
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM), tmp_path) == (None, ['remote_policy_cache_unreadable'])


@pytest.mark.parametrize('body', ['{not json', '[]', '"text"', '[' * 100000 + ']' * 100000])
def test_a_synced_cache_that_is_not_a_json_object_is_unreadable(machine, tmp_path, fast_sync, body):
    binary = fake_claude(tmp_path, doctor_out=TEAM, sync=body)
    assert why_of(binary, tmp_path) == (None, ['remote_policy_cache_unreadable'])


def test_a_sync_that_arrives_late_within_the_wait_still_counts(machine, tmp_path, fast_sync):
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM, sync='{}', sync_delay=0.6), tmp_path) == ({}, [])


def test_a_sync_that_never_arrives_is_pending(machine, tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, 'REMOTE_SETTINGS_SYNC_WAIT', 0.3)
    monkeypatch.setattr(profiles, 'REMOTE_SETTINGS_POLL', 0.05)
    old_cache(tmp_path)
    assert why_of(fake_claude(tmp_path, doctor_out=TEAM, sync='{}', sync_delay=2), tmp_path) == (None, ['remote_policy_sync_pending'])


@pytest.mark.parametrize('home', [None, '', 'relative/home'])
def test_the_home_must_come_from_the_restricted_environment(machine, tmp_path, fast_sync, home):
    binary = fake_claude(tmp_path, doctor_out=TEAM, sync='{}')
    env = {k: v for k, v in os.environ.items() if k != 'HOME'}
    if home is not None:
        env['HOME'] = home
    why = []
    assert profiles._effective_managed_policy(binary, env, str(tmp_path), why) is None
    assert why == ['remote_policy_home_unavailable']       # never the parent's own home


@pytest.mark.parametrize('out', [
    TEAM.replace('Loaded from api.anthropic.com', 'Loaded from somewhere else'),
    TEAM.replace('Loaded from api.anthropic.com', 'Loaded from api.anthropic.com and more'),
    TEAM.replace('checking… (fetch in progress; re-run in a moment)', 'loaded from claude.ai'),
    TEAM.replace('moment)', 'moment) and then more'),               # a suffix is not the documented wording
    TEAM.replace('checking…', 'checking'),
    TEAM + 'Organization policy: Not applicable to Pro and Max accounts\n',     # contradictory duplicate
    TEAM + 'Managed settings (remote): checking… (fetch in progress; re-run in a moment)\n',   # even a repeat
])
def test_only_the_exact_team_wording_is_accepted(machine, tmp_path, fast_sync, out):
    assert why_of(fake_claude(tmp_path, doctor_out=out, sync='{}'), tmp_path) == (None, ['doctor_unrecognized'])


def test_the_ascii_ellipsis_is_the_same_wording(machine, tmp_path, fast_sync):
    out = TEAM.replace('checking…', 'checking...')
    assert why_of(fake_claude(tmp_path, doctor_out=out, sync='{}'), tmp_path) == ({}, [])


def test_a_local_policy_still_wins_over_a_clean_synced_cache(machine, tmp_path, fast_sync):
    (machine / 'managed-settings.json').write_text('{"hooks": {"SessionStart": "x"}}')
    assert effective(fake_claude(tmp_path, doctor_out=TEAM, sync='{}'), tmp_path) == {'hooks': {'SessionStart': 'x'}}


def test_a_policy_that_is_not_a_json_object_in_a_local_source_is_unknown_even_when_deeply_nested(machine, tmp_path):
    (machine / 'managed-settings.json').write_text('[' * 100000 + ']' * 100000)
    assert effective(fake_claude(tmp_path), tmp_path) is None


def test_preflight_passes_a_team_account_with_a_synced_empty_cache_and_fails_when_it_holds_a_policy(machine, tmp_path, fast_sync):
    profiles.preflight(fake_claude(tmp_path, doctor_out=TEAM, sync='{}'), dict(os.environ), str(tmp_path))
    with pytest.raises(profiles.ProfileError) as caught:
        profiles.preflight(fake_claude(tmp_path, doctor_out=TEAM, sync='{"permissions": {"defaultMode": "bypassPermissions"}}'),
                           dict(os.environ), str(tmp_path))
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
