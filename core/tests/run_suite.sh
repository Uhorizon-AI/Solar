#!/usr/bin/env bash
# Run the whole core test suite (pytest + shell tests) in a clean environment.
#
# Same entrypoint for CI and for a maintainer who wants the CI result locally:
#   bash core/tests/run_suite.sh [pytest|shell|all|macos]   (default: all)
#
# `macos` is the macOS runner's job: only the pytest files whose behavior depends on
# macOS (launchd, LaunchAgents, case-insensitive volume, host lifecycle) plus every
# shell test. The full pytest suite runs on Ubuntu; running it twice on macOS would
# not fit the job limit and would repeat the same platform-neutral checks.
#
# Clean environment: every SOLAR_* variable of the caller is removed before a test runs
# (SOLAR_RUNTIME_ROOT, SOLAR_APP_DATA, SOLAR_TASK_ROOT... would point tests at a real
# runtime). Python tests run from a throwaway workspace (sun/ + .solar/settings.json)
# with SOLAR_ROOT pointing at this checkout; shell tests run with no SOLAR_* at all.
# The only one kept is the runner's own SOLAR_CI_SLOW_HEALTH_PROBE.
# The per-test limit of shell tests needs `timeout` (Ubuntu) or `gtimeout` (macOS with
# coreutils; the workflow installs it). Without either there is no per-test limit and
# only the job limit applies; the run says so.
# pytest runs in parallel (SOLAR_TEST_WORKERS, default 4; 1 = serial); see the serial mark.
# The smoke script core/tests/skills/solar-gateway/smoke_priority_ensure.sh is not named
# test_* and needs a live gateway, so it is not run here.
# A test that cannot run on a runner goes in SKIPS below with a reason; it is
# printed on every run, never silently dropped.
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../.." && pwd)"
MODE="${1:-all}"
SHELL_TIMEOUT="${SOLAR_SHELL_TEST_TIMEOUT:-300}"

# `-u NAME` for every inherited SOLAR_* variable except the runner's own marker.
SCRUB=()
while IFS= read -r _name; do
  [[ "$_name" == SOLAR_CI_SLOW_HEALTH_PROBE ]] || SCRUB+=(-u "$_name")
done < <(env | sed -n 's/^\(SOLAR_[A-Za-z0-9_]*\)=.*/\1/p')

# Pytest files that depend on macOS, relative to core/tests.
MACOS_PYTEST=(
  skills/solar-system
  skills/solar-app/test_host_lifecycle.py
  skills/solar-client/test_service_isolation.py
  skills/solar-client/test_smoke_isolation.py
  skills/solar-client/test_update_sequence.py
  skills/solar-client/test_codex_agents.py
  skills/solar-router/test_runtime_isolation.py
)

# "relative/path.sh|reason" — explicit skips for tests that cannot run on a CI runner.
SKIPS=(
)

# Per-test time limit when a timeout binary exists (Ubuntu: timeout; macOS: gtimeout if installed).
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"

skip_reason() {
  local rel="$1" entry
  for entry in "${SKIPS[@]+"${SKIPS[@]}"}"; do
    [[ "${entry%%|*}" == "$rel" ]] && { echo "${entry#*|}"; return 0; }
  done
  return 1
}

# Workers for pytest (xdist). SOLAR_TEST_WORKERS=1 runs everything serially.
WORKERS="${SOLAR_TEST_WORKERS:-4}"

run_pytest() {
  local ws rc targets=("$TESTS_DIR") t
  if [[ "${1:-}" == macos ]]; then
    targets=()
    for t in "${MACOS_PYTEST[@]}"; do targets+=("$TESTS_DIR/$t"); done
  fi
  ws="$(mktemp -d)"
  mkdir -p "$ws/sun" "$ws/.solar"
  echo '{}' > "$ws/.solar/settings.json"
  echo "== pytest (workspace fixture: $ws)"
  (
    cd "$ws" || exit 2
    pt() { env ${SCRUB[@]+"${SCRUB[@]}"} SOLAR_ROOT="$REPO_ROOT" \
      uv run --project "$TESTS_DIR" pytest "${targets[@]}" -p no:cacheprovider -q -ra --durations=20 "${PYTEST_EXTRA_ARGS[@]+"${PYTEST_EXTRA_ARGS[@]}"}" "$@"; }
    if [[ "$WORKERS" -gt 1 ]]; then
      # Whole files go to one worker (--dist loadfile), so tests of a file never overlap.
      # A test that is not safe next to other files carries @pytest.mark.serial and its
      # reason; those run alone in the second pass (exit 5 = none collected, fine).
      # Both passes always run, so one failing pass never hides the other's result.
      pt -n "$WORKERS" --dist loadfile -m "not serial"; r1=$?
      pt -m serial; r2=$?
      [[ "$r2" -eq 5 ]] && r2=0
      (( r1 != 0 )) && exit "$r1"
      exit "$r2"
    fi
    pt
  )
  rc=$?
  rm -rf "$ws"
  return "$rc"
}

# Gateway bridges (and the uv wrappers that start them) still alive: pid, parent, command.
bridge_procs() {
  ps -axo pid,ppid,command | grep -E 'websockets==12|run_(http_webhook|websocket)_bridge' | grep -v grep || true
}

# Print any bridge process that was not alive in the snapshot $2 (taken before $1 ran).
report_leak() {
  local what="$1" before="$2" now
  now="$(bridge_procs)"
  [[ "$now" == "$before" ]] && return 0
  echo "LEAK after $what: gateway bridge processes left alive:"
  diff <(printf '%s\n' "$before") <(printf '%s\n' "$now") | sed -n 's/^> /  /p'
}

run_shell() {
  local failed=() skipped=() passed=0 f rel reason
  echo "== shell tests"
  [[ -n "$TIMEOUT_BIN" ]] || echo "note: no timeout or gtimeout found; shell tests have no per-test limit"
  cd "$REPO_ROOT" || return 2
  while IFS= read -r f; do
    rel="${f#"$REPO_ROOT"/}"
    if reason="$(skip_reason "${rel#core/tests/}")"; then
      echo "SKIP $rel: $reason"; skipped+=("$rel"); continue
    fi
    echo "-- $rel"
    _before="$(bridge_procs)"
    if env ${SCRUB[@]+"${SCRUB[@]}"} ${TIMEOUT_BIN:+"$TIMEOUT_BIN" "$SHELL_TIMEOUT"} bash "$f"; then
      passed=$((passed + 1))
    else
      echo "FAIL $rel"; failed+=("$rel")
    fi
    report_leak "$rel" "$_before"
  done < <(find "$TESTS_DIR" -type f -name 'test_*.sh' | sort)
  # Guard against a discovery that silently finds nothing (a moved directory, a wrong glob).
  (( passed + ${#failed[@]} + ${#skipped[@]} >= 20 )) || { echo "FAIL: found fewer than 20 shell tests"; return 1; }
  echo "shell: passed=$passed failed=${#failed[@]} skipped=${#skipped[@]}"
  ((${#failed[@]} == 0)) || { printf 'FAILED: %s\n' "${failed[@]}"; return 1; }
}

# pytest, with the same leftover-process check the shell tests get.
pytest_pass() {
  local before; before="$(bridge_procs)"
  run_pytest "$@"; local r=$?
  report_leak "the pytest pass" "$before"
  return "$r"
}

rc=0
case "$MODE" in
  pytest) pytest_pass || rc=1 ;;
  shell) run_shell || rc=1 ;;
  all) pytest_pass || rc=1; run_shell || rc=1 ;;
  macos) export SOLAR_CI_SLOW_HEALTH_PROBE=1; pytest_pass macos || rc=1; run_shell || rc=1 ;;
  *) echo "usage: $0 [pytest|shell|all|macos]" >&2; exit 2 ;;
esac
exit "$rc"
