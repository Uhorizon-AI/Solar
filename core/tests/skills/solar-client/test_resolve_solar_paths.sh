#!/usr/bin/env bash
# Unit tests for resolve_solar_paths.sh (canonical: solar-client)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPT="$(cd "$SCRIPT_DIR/../../../skills/solar-client/scripts" && pwd)/resolve_solar_paths.sh"
GLOBAL_ROOT="$(cd "$(dirname "$RESOLVE_SCRIPT")/../../../.." && pwd)"
PASS=0
FAIL=0

_assert_run() {
  local out_file="$1"
  shift
  local code=0
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
  unset SOLAR_WORKSPACE SOLAR_ROOT
  solar_resolve_paths --quiet "$@"
}

run_resolve_keep_env() {
  # shellcheck source=/dev/null
  source "$RESOLVE_SCRIPT"
  solar_resolve_paths --quiet "$@"
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

NEW_WS="$TMP/new-workspace"
mkdir -p "$NEW_WS/sun" "$NEW_WS/.solar"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$NEW_WS/.solar/manifest.json"

DECOY="$TMP/decoy-dot-solar"
mkdir -p "$DECOY/.solar" "$DECOY/sub/deep"
pushd "$DECOY/sub/deep" >/dev/null
assert_fail "ignore .solar without manifest+sun" run_resolve
popd >/dev/null

mkdir -p "$NEW_WS/sub/deep"
pushd "$NEW_WS/sub/deep" >/dev/null
assert_ok "discovery manifest workspace from subdir" run_resolve
expected_ws="$(cd "$NEW_WS" && pwd -P)"
expected_root="$(cd "$GLOBAL_ROOT" && pwd -P)"
if [[ "${SOLAR_WORKSPACE:-}" != "$expected_ws" ]]; then
  echo "FAIL: SOLAR_WORKSPACE mismatch for v1.1 layout" >&2
  FAIL=$((FAIL + 1))
fi
if [[ "${SOLAR_ROOT:-}" != "$expected_root" ]]; then
  echo "FAIL: SOLAR_ROOT should be install root ($expected_root), got ${SOLAR_ROOT:-}" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

OBSOLETE="$TMP/obsolete-core"
mkdir -p "$OBSOLETE/.solar/core" "$OBSOLETE/sun"
echo '{"layout":"solar-client-v1"}' > "$OBSOLETE/.solar/manifest.json"
pushd "$OBSOLETE" >/dev/null
assert_fail "strict fails on .solar/core" run_resolve
popd >/dev/null

pushd "$OBSOLETE" >/dev/null
assert_ok "relaxed allows .solar/core during upgrade" run_resolve --relaxed
popd >/dev/null

LEG_WS="$TMP/legacy-workspace"
mkdir -p "$LEG_WS/core/skills"
echo "# Core" > "$LEG_WS/core/AGENTS.md"
mkdir -p "$LEG_WS/sun"
pushd "$LEG_WS" >/dev/null
assert_ok "discovery legacy core/" run_resolve
expected_legacy_root="$(cd "$LEG_WS" && pwd -P)"
if [[ "${SOLAR_ROOT:-}" != "$expected_legacy_root" ]]; then
  echo "FAIL: SOLAR_ROOT mismatch for legacy (expected $expected_legacy_root)" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

SOLAR_WS="$TMP/solar-subtree"
mkdir -p "$SOLAR_WS/solar/core/skills" "$SOLAR_WS/sun"
echo "# Core" > "$SOLAR_WS/solar/core/AGENTS.md"
pushd "$SOLAR_WS" >/dev/null
assert_ok "discovery legacy solar/core" run_resolve
expected_solar_root="$(cd "$SOLAR_WS/solar" && pwd -P)"
if [[ "${SOLAR_ROOT:-}" != "$expected_solar_root" ]]; then
  echo "FAIL: SOLAR_ROOT mismatch for solar/ install ($expected_solar_root)" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

WS_A="$TMP/workspace-a"
WS_B="$TMP/workspace-b"
mkdir -p "$WS_A/.solar" "$WS_A/sun"
echo '{"layout":"solar-client-v1.1"}' > "$WS_A/.solar/manifest.json"
mkdir -p "$WS_B/.solar" "$WS_B/sun"
echo '{"layout":"solar-client-v1.1"}' > "$WS_B/.solar/manifest.json"
export SOLAR_WORKSPACE="$WS_A"
pushd "$WS_B" >/dev/null
assert_fail "conflict export A cwd B" run_resolve_keep_env
popd >/dev/null
unset SOLAR_WORKSPACE

pushd /tmp >/dev/null
assert_ok "--workspace forces workspace" run_resolve --workspace "$NEW_WS"
if [[ "${SOLAR_WORKSPACE:-}" != "$(cd "$NEW_WS" && pwd -P)" ]]; then
  echo "FAIL: --workspace did not set SOLAR_WORKSPACE" >&2
  FAIL=$((FAIL + 1))
fi
popd >/dev/null

mkdir -p "$TMP/empty-nowhere"
pushd "$TMP/empty-nowhere" >/dev/null
assert_fail "no workspace" run_resolve
popd >/dev/null

echo "---"
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
