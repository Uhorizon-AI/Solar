#!/usr/bin/env bash
# Smoke tests for resolve_solar_home.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../../skills/solar-interface/scripts" && pwd)/resolve_solar_home.sh"
PASS=0
FAIL=0

# Run in current shell (not $(...)) so solar_resolve_home exports persist for follow-up checks.
_assert_run() {
  local out_file="$1"
  shift
  local code=0
  # Do not use `if cmd; then ...; return $?` — after a failed `if`, $? is often 0 in bash.
  "$@" >"$out_file" 2>&1 || code=$?
  return "$code"
}

_assert_print_output() {
  local out_file="$1"
  if [[ -s "$out_file" ]]; then
    echo "  output:" >&2
    sed 's/^/    /' "$out_file" >&2
  fi
}

assert_ok() {
  local label="$1"
  shift
  local out_file
  out_file="$(mktemp)"
  if _assert_run "$out_file" "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
    rm -f "$out_file"
    return 0
  fi
  echo "FAIL: $label" >&2
  _assert_print_output "$out_file"
  rm -f "$out_file"
  FAIL=$((FAIL + 1))
  return 1
}

assert_fail() {
  local label="$1"
  shift
  local out_file
  out_file="$(mktemp)"
  if _assert_run "$out_file" "$@"; then
    echo "FAIL: $label (expected failure, got success)" >&2
    _assert_print_output "$out_file"
    rm -f "$out_file"
    FAIL=$((FAIL + 1))
    return 1
  fi
  echo "PASS: $label"
  PASS=$((PASS + 1))
  rm -f "$out_file"
  return 0
}

run_resolve() {
  # shellcheck source=/dev/null
  source "$RESOLVE_SCRIPT"
  unset SOLAR_HOME SOLAR_CORE_ROOT REPO_ROOT
  solar_resolve_home --quiet "$@"
}

run_resolve_keep_env() {
  # shellcheck source=/dev/null
  source "$RESOLVE_SCRIPT"
  solar_resolve_home --quiet "$@"
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# New layout: .solar/
NEW_WS="$TMP/new-workspace"
mkdir -p "$NEW_WS/.solar/core/skills"

# decoy: .solar without core/ must not match
DECOY="$TMP/decoy-dot-solar"
mkdir -p "$DECOY/.solar" "$DECOY/sub/deep"
pushd "$DECOY/sub/deep" >/dev/null
assert_fail "ignore .solar without core/" run_resolve
popd >/dev/null

mkdir -p "$NEW_WS/sun"
mkdir -p "$NEW_WS/sub/deep"
pushd "$NEW_WS/sub/deep" >/dev/null
assert_ok "discovery .solar from subdir" run_resolve
expected_home="$(cd "$NEW_WS" && pwd -P)"
expected_core="$(cd "$NEW_WS/.solar/core" && pwd -P)"
if [[ "${SOLAR_HOME:-}" != "$expected_home" ]]; then
  echo "FAIL: SOLAR_HOME mismatch for .solar layout" >&2
  FAIL=$((FAIL + 1))
fi
if [[ "${SOLAR_CORE_ROOT:-}" != "$expected_core" ]]; then
  echo "FAIL: SOLAR_CORE_ROOT mismatch for .solar layout" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

# Legacy layout: core/ at root
LEG_WS="$TMP/legacy-workspace"
mkdir -p "$LEG_WS/core/skills"
echo "# Core" > "$LEG_WS/core/AGENTS.md"
mkdir -p "$LEG_WS/sun"
pushd "$LEG_WS" >/dev/null
assert_ok "discovery legacy core/" run_resolve
expected_legacy_core="$(cd "$LEG_WS/core" && pwd -P)"
if [[ "${SOLAR_CORE_ROOT:-}" != "$expected_legacy_core" ]]; then
  echo "FAIL: SOLAR_CORE_ROOT mismatch for legacy" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

# Anti-contamination
WS_A="$TMP/workspace-a"
WS_B="$TMP/workspace-b"
mkdir -p "$WS_A/.solar/core" "$WS_A/sun"
mkdir -p "$WS_B/.solar/core" "$WS_B/sun"
export SOLAR_HOME="$WS_A"
pushd "$WS_B" >/dev/null
assert_fail "conflict export A cwd B" run_resolve_keep_env
popd >/dev/null
unset SOLAR_HOME

# --home override
pushd /tmp >/dev/null
assert_ok "--home forces workspace" run_resolve --home "$NEW_WS"
if [[ "${SOLAR_HOME:-}" != "$(cd "$NEW_WS" && pwd -P)" ]]; then
  echo "FAIL: --home did not set SOLAR_HOME" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

# No workspace
mkdir -p "$TMP/empty-nowhere"
pushd "$TMP/empty-nowhere" >/dev/null
assert_fail "no workspace" run_resolve
popd >/dev/null

echo "---"
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
