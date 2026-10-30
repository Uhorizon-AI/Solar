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
# Clean environment: nothing is inherited from the caller's Solar setup. Python
# tests run from a throwaway workspace (sun/ + .solar/settings.json) with
# SOLAR_ROOT pointing at this checkout; shell tests run with both variables unset.
# A test that cannot run on a runner goes in SKIPS below with a reason; it is
# printed on every run, never silently dropped.
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../.." && pwd)"
MODE="${1:-all}"
SHELL_TIMEOUT="${SOLAR_SHELL_TEST_TIMEOUT:-300}"

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
    env -u SOLAR_WORKSPACE SOLAR_ROOT="$REPO_ROOT" \
      uv run --project "$TESTS_DIR" pytest "${targets[@]}" -p no:cacheprovider -q -ra --durations=20 "${PYTEST_EXTRA_ARGS[@]+"${PYTEST_EXTRA_ARGS[@]}"}"
  )
  rc=$?
  rm -rf "$ws"
  return "$rc"
}

run_shell() {
  local failed=() skipped=() passed=0 f rel reason
  echo "== shell tests"
  cd "$REPO_ROOT" || return 2
  while IFS= read -r f; do
    rel="${f#"$REPO_ROOT"/}"
    if reason="$(skip_reason "${rel#core/tests/}")"; then
      echo "SKIP $rel: $reason"; skipped+=("$rel"); continue
    fi
    echo "-- $rel"
    if env -u SOLAR_WORKSPACE -u SOLAR_ROOT ${TIMEOUT_BIN:+"$TIMEOUT_BIN" "$SHELL_TIMEOUT"} bash "$f"; then
      passed=$((passed + 1))
    else
      echo "FAIL $rel"; failed+=("$rel")
    fi
  done < <(find "$TESTS_DIR" -type f -name 'test_*.sh' | sort)
  echo "shell: passed=$passed failed=${#failed[@]} skipped=${#skipped[@]}"
  ((${#failed[@]} == 0)) || { printf 'FAILED: %s\n' "${failed[@]}"; return 1; }
}

rc=0
case "$MODE" in
  pytest) run_pytest || rc=1 ;;
  shell) run_shell || rc=1 ;;
  all) run_pytest || rc=1; run_shell || rc=1 ;;
  macos) export SOLAR_CI_SLOW_HEALTH_PROBE=1; run_pytest macos || rc=1; run_shell || rc=1 ;;
  *) echo "usage: $0 [pytest|shell|all|macos]" >&2; exit 2 ;;
esac
exit "$rc"
