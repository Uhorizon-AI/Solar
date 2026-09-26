#!/usr/bin/env bash
# Abort a shell test that would use the machine runtime or the real launchctl.
# Source this file and call solar_test_guard after pointing SOLAR_RUNTIME_ROOT
# (or SOLAR_APP_DATA) at a temp dir and launchctl at a test double.

_SOLAR_TEST_GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

solar_test_runtime_py() {
  printf '%s\n' "$_SOLAR_TEST_GUARD_DIR/../../skills/solar-paths/scripts/solar_runtime.py"
}

# The machine default, from solar-paths, with test overrides removed.
solar_test_live_runtime() {
  local py out
  py="$(solar_test_runtime_py)"
  if [[ ! -f "$py" ]]; then
    echo "ABORT: solar_runtime.py not found ($py)." >&2
    exit 97
  fi
  if ! out="$(env -u SOLAR_RUNTIME_ROOT -u SOLAR_APP_DATA python3 "$py" runtime)"; then
    echo "ABORT: could not resolve the live Solar runtime." >&2
    exit 97
  fi
  printf '%s\n' "$out"
}

# What this test would use. solar_runtime.py applies SOLAR_RUNTIME_ROOT and SOLAR_APP_DATA.
solar_test_resolved_runtime() {
  local py out
  py="$(solar_test_runtime_py)"
  if ! out="$(python3 "$py" runtime)"; then
    echo "ABORT: could not resolve the test runtime." >&2
    exit 97
  fi
  printf '%s\n' "$out"
}

solar_test_guard() {
  local live resolved lc
  live="$(solar_test_live_runtime)"
  resolved="$(solar_test_resolved_runtime)"
  live="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$live")"
  resolved="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$resolved")"
  if [[ "$resolved" == "$live" ]]; then
    echo "ABORT: this test would use the live Solar runtime ($live)." >&2
    echo "Set SOLAR_RUNTIME_ROOT or SOLAR_APP_DATA to a temporary directory." >&2
    exit 97
  fi
  if [[ -n "${SOLAR_CLIENT_LAUNCHCTL:-}" ]]; then
    lc="$SOLAR_CLIENT_LAUNCHCTL"
  else
    lc="$(command -v launchctl || true)"
  fi
  case "$lc" in
    /bin/launchctl|/usr/bin/launchctl)
      echo "ABORT: launchctl is the system binary ($lc)." >&2
      echo "Point SOLAR_CLIENT_LAUNCHCTL or PATH at a test double." >&2
      exit 97
      ;;
    "")
      ;;
    *)
      if [[ ! -f "$lc" ]]; then
        echo "ABORT: launchctl test double is missing ($lc)." >&2
        exit 97
      fi
      ;;
  esac
  return 0
}
