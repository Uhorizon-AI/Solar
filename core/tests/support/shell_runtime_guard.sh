#!/usr/bin/env bash
# Abort a shell test that would use the machine runtime or the real launchctl.
# Source this file and call solar_test_guard after pointing SOLAR_RUNTIME_ROOT
# (or SOLAR_APP_DATA) at a temp dir and launchctl at a test double.
#
# solar_test_guard runs two unconditional checks: the resolved runtime must not
# be the machine runtime, and launchctl must not be the system binary. A third
# check is opt-in with `solar_test_guard --services`: it aborts a test that
# would run the state cutover against the live global install without pinning
# service detection. Only tests that reach solar_client_state_cutover (a full
# client_sync.sh run) need it; tests that never get there keep the two checks.

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

# The Client's global install, resolved with the test's own overrides.
# SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE (including empty) wins, exactly as it
# does for the Client: this renders the same resolution production uses.
solar_test_global_install() {
  local script out
  script="$(cd "$_SOLAR_TEST_GUARD_DIR/../../skills/solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
  if [[ ! -f "$script" ]]; then
    echo "ABORT: resolve_solar_paths.sh not found ($script)." >&2
    exit 97
  fi
  if ! out="$(bash -c 'source "$1"; solar_global_install_root' _ "$script" 2>/dev/null)"; then
    return 1
  fi
  [[ -n "$out" ]] || return 1
  printf '%s\n' "$out"
}

# The install a sync hands to solar_client_state_cutover: SOLAR_ROOT, which is
# what client_sync.sh captures as SYNC_INSTALL_ROOT. Without SOLAR_ROOT the
# Client resolves the same global install solar-paths returns.
solar_test_effective_install() {
  if [[ -n "${SOLAR_ROOT:-}" ]]; then
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SOLAR_ROOT"
    return 0
  fi
  solar_test_global_install
}

# Opt-in third check (solar_test_guard --services). A test that may reach
# solar_client_state_cutover must not point at the machine's real global
# install unless service detection is pinned, because the cutover reads
# running services from that install and stops them. The override covers
# detection only: the LaunchAgent bootout/bootstrap stays reachable, so the
# launchctl double is still required.
#
# "Live global install" is decided on physical paths: the realpath of the
# effective install is compared against the realpath of the Client's global
# install (SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE when pinned, otherwise the one
# solar-paths resolves). Never a string match.
solar_test_guard_services() {
  local effective live
  # Defined-but-empty counts as pinned, exactly as the Client reads it
  # (`${SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE-__UNSET__}`): a defined value makes
  # the Client skip detection, empty included.
  if [[ -n "${SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE+x}" || -n "${SOLAR_CLIENT_PS_OUTPUT_FILE:-}" ]]; then
    return 0
  fi
  if ! effective="$(solar_test_effective_install)"; then
    echo "ABORT: could not resolve the effective install for the service check." >&2
    exit 97
  fi
  if ! live="$(solar_test_global_install)"; then
    echo "ABORT: could not resolve the Client's global install for the service check." >&2
    exit 97
  fi
  if [[ -z "$effective" || -z "$live" ]]; then
    echo "ABORT: the service check could not resolve an install to compare (effective='$effective' global='$live')." >&2
    exit 97
  fi
  effective="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$effective")"
  live="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$live")"
  if [[ "$effective" == "$live" ]]; then
    echo "ABORT: this test would run the state cutover against the live global install ($live)." >&2
    echo "Set SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none (or SOLAR_CLIENT_PS_OUTPUT_FILE) and keep the launchctl double." >&2
    exit 97
  fi
  return 0
}

solar_test_guard() {
  local with_services=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --services) with_services=true; shift ;;
      *) echo "ABORT: unknown solar_test_guard option: $1" >&2; exit 97 ;;
    esac
  done
  local live resolved lc
  # `|| exit 97` is required: a bare `$(...)` would only leave the subshell, and
  # the guard would carry on with an empty value (a fail-open). Empty results
  # abort too: `realpath ""` is the cwd, so comparing two empty values would pass.
  live="$(solar_test_live_runtime)" || exit 97
  resolved="$(solar_test_resolved_runtime)" || exit 97
  if [[ -z "$live" || -z "$resolved" ]]; then
    echo "ABORT: the guard could not resolve the runtime to compare (live='$live' resolved='$resolved')." >&2
    exit 97
  fi
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
  if [[ "$with_services" == true ]]; then
    solar_test_guard_services
  fi
  return 0
}
