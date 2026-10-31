"""Exercise cleanup decisions with fake process tables, never real signals."""
from pathlib import Path
import subprocess

import pytest


TESTS = Path(__file__).resolve().parents[2]
GATEWAY = Path(__file__).with_name("test_gateway_lifecycle.sh")


def helpers(path, start, end):
    return path.read_text().split(start, 1)[1].split(end, 1)[0]


def shell(code):
    result = subprocess.run(["bash", "-c", "set -euo pipefail\n" + code],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def cleanup_helpers():
    return "owned_bridges()" + helpers(GATEWAY, "owned_bridges()", '\nTMP="$(mktemp')


@pytest.mark.parametrize("file,owned", [
    ("/tmp/test.fixture/run/http.log", True),
    ("/tmp/testXfixture/run/http.log", False),
    ("/tmp/test.fixture-other/run/http.log", False),
    ("/unrelated/run/http.log", False),
])
def test_only_a_file_in_the_test_directory_proves_ownership(file, owned):
    # lsof reports a foreign bridge on a fixed test port in every case. Port
    # reuse must never be sufficient to authorize a signal.
    output = shell(cleanup_helpers() + f'''
TMP=/tmp/test.fixture
TMP_REAL="$TMP"
BRIDGES_BEFORE=""
bridge_pids() {{ echo 200; }}
bridge_ident() {{ echo identity-200; }}
ps() {{ :; }}
lsof() {{
  if [[ "$*" == *-iTCP:* ]]; then echo 200;
  else printf '%s\\n' 'n{file}'; fi
}}
owned_bridges
''')
    assert ("200\tidentity-200" in output) is owned


def test_a_preexisting_bridge_is_excluded_even_with_an_open_test_file():
    output = shell(cleanup_helpers() + '''
TMP=/tmp/test.fixture
TMP_REAL="$TMP"
BRIDGES_BEFORE=200
bridge_pids() { echo 200; }
bridge_ident() { echo identity-200; }
ps() { :; }
lsof() { echo n/tmp/test.fixture/run/http.log; }
owned_bridges
''')
    assert output == ""


def test_cleanup_rechecks_identity_before_kill():
    output = shell(cleanup_helpers() + '''
owned_bridges() { printf '200\\tidentity-200\\n'; }
explain_unowned_bridges() { :; }
bridge_ident() {
  if [[ "$reused" == yes ]]; then echo replacement; else echo identity-200; fi
}
kill() { echo "signal $*"; }
sleep() { reused=yes; }
reused=no
kill_leftover_bridges
''')
    assert output.splitlines() == ["signal -TERM 200"]


@pytest.mark.parametrize("now,expected", [
    ("", False),
    ("100 9 bridge", False),  # reparenting is not a new process
    ("200 1 bridge\n100 1 bridge", True),
])
def test_leak_check_only_reports_new_pids_and_fails_ci(now, expected):
    suite = TESTS / "run_suite.sh"
    code = "snapshot_pids()" + helpers(suite, "snapshot_pids()", "\nrun_shell()")
    output = shell(code + f'''
CI=true
bridge_procs() {{ printf '%s\\n' '{now}'; }}
if report_leak example '100 1 bridge'; then echo clean; else echo failed; fi
''')
    assert ("LEAK after" in output) is expected
    assert output.rstrip().endswith("failed" if expected else "clean")
