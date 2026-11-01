#!/usr/bin/env bash
# Run the whole core test suite (pytest + shell tests) in a clean environment.
#
# Same entrypoint for CI and for a maintainer who wants the CI result locally:
#   bash core/tests/run_suite.sh [pytest|shell|all|macos]   (default: all)
#
# `macos` is the macOS runner's job: only the pytest files whose behavior depends on
# macOS (launchd, LaunchAgents, case-insensitive volume, host lifecycle), focused
# supervisor recovery regressions, and every shell test. The full pytest suite runs on Ubuntu;
# running it twice on macOS would
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
# After every shell test and after the pytest pass the runner looks for gateway bridge
# processes (uv run --with websockets==12.0 ... run_*_bridge) that were not alive before it.
# In CI (GITHUB_ACTIONS or CI set) a new one fails the run; on a developer machine it only
# prints LEAK, so a real gateway started meanwhile never gives a false failure.
# CI also stops new leaked bridges, rechecking start time and command before each signal.
# This releases uv cache locks even when the individual test lost track of its wrapper.
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

# macOS targets plus recovery regressions checked on both OSes, relative to core/tests.
MACOS_PYTEST=(
  skills/solar-async-tasks/test_supervisor_recovery_identity.py
  skills/solar-async-tasks/test_supervisor_lifecycle.py::test_an_execution_lost_with_its_supervisor_is_failed_not_run_again
  skills/solar-async-tasks/test_supervisor_recovery.py::test_an_executor_that_hangs_before_taking_its_execution_is_stopped_when_its_lease_runs_out
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
      # The second pass collects the whole suite again and keeps only `serial`. That is deliberate:
      # it is simpler than listing files, and a serial mark on a single parameter or test (not
      # a whole file) can never be missed.
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

# Gateway bridges (and the uv wrappers that start them) alive now: "pid ppid command" lines,
# sorted by pid. `ps -axww` so a long command line is never cut (same as port_watch.py).
bridge_procs() {
  ps -axww -o pid=,ppid=,command= \
    | awk '/websockets==12|run_(http_webhook|websocket)_bridge/ && !/awk/' | sort -n || true
}

# The pids of a bridge_procs snapshot, one per line.
snapshot_pids() { printf '%s\n' "$1" | awk 'NF {print $1}' | sort; }

# A nonempty identity is returned only while this PID is still a gateway bridge.
bridge_identity() {
  ps -ww -p "$1" -o lstart= -o command= 2>/dev/null \
    | awk '/websockets==12|run_(http_webhook|websocket)_bridge/ && !/awk/' \
    | sed 's/  */ /g' || true
}

# Only used on dedicated CI runners. Capture identities before sending any signal,
# then check them again before TERM and KILL to avoid signalling reused PIDs.
cleanup_ci_bridges() {
  local pids="$1" owned="" pid ident sig
  for pid in $pids; do
    ident="$(bridge_identity "$pid")"
    [[ -n "$ident" ]] && owned+="$pid"$'\t'"$ident"$'\n'
  done
  [[ -n "$owned" ]] || return 0
  for sig in TERM KILL; do
    while IFS=$'\t' read -r pid ident; do
      [[ -n "$pid" && -n "$ident" ]] || continue
      [[ "$(bridge_identity "$pid")" == "$ident" ]] || continue
      kill -"$sig" "$pid" 2>/dev/null || true
    done <<<"$owned"
    if [[ "$sig" == TERM ]]; then sleep 1; fi
  done
  return 0
}

# A bridge process that was not alive in snapshot $2 (taken before $1 ran) is a leak. Only a NEW
# pid counts: a process that went away, or whose parent or position in the list changed, does
# not. A leak is printed as LEAK; in CI (GITHUB_ACTIONS or CI set) it also fails the run,
# because a runner has no real gateway of its own. On a developer machine it only warns: a
# real gateway started meanwhile must not turn a local run red. Returns 1 for a failing leak.
report_leak() {
  local what="$1" before="$2" now new pid
  now="$(bridge_procs)"
  new="$(comm -13 <(snapshot_pids "$before") <(snapshot_pids "$now"))"
  [[ -n "$new" ]] || return 0
  echo "LEAK after $what: gateway bridge processes left alive:"
  for pid in $new; do printf '%s\n' "$now" | awk -v p="$pid" '$1 == p {print "  " $0}'; done
  [[ -n "${GITHUB_ACTIONS:-}${CI:-}" ]] || return 0
  cleanup_ci_bridges "$new"
  return 1
}

run_shell() {
  local failed=() skipped=() passed=0 f rel reason _before test_rc
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
    test_rc=0
    env ${SCRUB[@]+"${SCRUB[@]}"} ${TIMEOUT_BIN:+"$TIMEOUT_BIN" "$SHELL_TIMEOUT"} bash "$f" || test_rc=$?
    report_leak "$rel" "$_before" || { test_rc=1; echo "FAIL $rel: left gateway processes alive"; }
    if (( test_rc == 0 )); then
      passed=$((passed + 1))
    else
      echo "FAIL $rel"; failed+=("$rel")
    fi
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
  report_leak "the pytest pass" "$before" || r=1
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
