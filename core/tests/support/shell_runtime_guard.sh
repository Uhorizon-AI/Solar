#!/usr/bin/env bash
# Abort a shell test that would use the machine runtime or the real launchctl.
# Source this file and call solar_test_guard after pointing SOLAR_RUNTIME_ROOT
# (or SOLAR_APP_DATA) at a temp dir and launchctl at a test double.
#
# solar_test_guard --services is an explicit opt-in extra check for tests that
# run the whole client_sync.sh / client_update.sh path (which ends in the state
# cutover that stops and starts real services). It is NOT automatic: call it
# AFTER SOLAR_ROOT, the service-detection hooks and the global-install pin are
# set. Contract: core/docs/test-isolation.md.

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

# Physical path (realpath), never the string received.
solar_test_physical() {
  python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

# The real global install: SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE when set (an
# empty value means "no global install"), otherwise the install the framework
# itself resolves (solar_global_install_root). Prints a physical path, or
# nothing when there is none.
solar_test_global_install() {
  local root
  if [[ -n "${SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE+x}" && -z "${SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE}" ]]; then
    return 0
  fi
  root="$(bash -c 'source "$1"; solar_global_install_root' _ \
    "$_SOLAR_TEST_GUARD_DIR/../../skills/solar-paths/scripts/resolve_solar_paths.sh" 2>/dev/null || true)"
  [[ -n "$root" ]] || return 0
  solar_test_physical "$root"
}

# The install whose scripts the cutover would detect and stop: SOLAR_ROOT, or the
# repository this guard belongs to when SOLAR_ROOT is not set.
solar_test_effective_install() {
  solar_test_physical "${SOLAR_ROOT:-$_SOLAR_TEST_GUARD_DIR/../../..}"
}

# --services: service detection must be disabled or simulated, or the effective
# install must not be the real global install. Never exits the caller's shell on
# its own: returns 97 after printing the reason; solar_test_guard exits.
solar_test_guard_services() {
  local override="${SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE-__UNSET__}" effective global services=""
  if [[ "$override" != "__UNSET__" ]]; then
    [[ "$override" == "none" ]] || services="$override"
  elif [[ -n "${SOLAR_CLIENT_PS_OUTPUT_FILE:-}" && -f "${SOLAR_CLIENT_PS_OUTPUT_FILE}" ]]; then
    # A simulated process table is judged by what it makes the cutover detect for the
    # effective install (as given and as a physical path), like the cutover itself.
    local root phys
    phys="$(solar_test_effective_install)"
    for root in "${SOLAR_ROOT:-$phys}" "$phys"; do
      root="${root%/}"
      grep -qF "$root/core/skills/solar-app/scripts/host_server.py" "$SOLAR_CLIENT_PS_OUTPUT_FILE" \
        && [[ ",$services," != *",host,"* ]] && services="${services:+$services,}host"
      if grep -qF -e "$root/core/skills/solar-gateway/scripts/run_http_webhook_bridge.py" \
          -e "$root/core/skills/solar-gateway/scripts/run_websocket_bridge.py" "$SOLAR_CLIENT_PS_OUTPUT_FILE" \
          && [[ ",$services," != *",gateway,"* ]]; then
        services="${services:+$services,}gateway"
      fi
    done
  fi
  if [[ "$override" != "__UNSET__" || -n "${SOLAR_CLIENT_PS_OUTPUT_FILE:-}" && -f "${SOLAR_CLIENT_PS_OUTPUT_FILE:-/nonexistent}" ]]; then
    # A detected service is stopped and started through hooks: they must be set too.
    if [[ ",$services," == *",host,"* ]] \
      && [[ -z "${SOLAR_CLIENT_HOST_STOP_SCRIPT:-}" || -z "${SOLAR_CLIENT_HOST_START_SCRIPT:-}" ]]; then
      echo "ABORT: a simulated 'host' service needs SOLAR_CLIENT_HOST_STOP_SCRIPT and SOLAR_CLIENT_HOST_START_SCRIPT." >&2
      return 97
    fi
    if [[ ",$services," == *",gateway,"* ]] \
      && [[ -z "${SOLAR_CLIENT_GATEWAY_STOP_SCRIPT:-}" || -z "${SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT:-}" ]]; then
      echo "ABORT: a simulated 'gateway' service needs SOLAR_CLIENT_GATEWAY_STOP_SCRIPT and SOLAR_CLIENT_GATEWAY_SETUP_SCRIPT." >&2
      return 97
    fi
    return 0
  fi
  effective="$(solar_test_effective_install)"
  global="$(solar_test_global_install)"
  if [[ -n "$global" && "$effective" == "$global" ]]; then
    echo "ABORT: service detection is real and the effective install ($effective) is the real global install." >&2
    echo "Set SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none (or SOLAR_CLIENT_PS_OUTPUT_FILE), or pin" >&2
    echo "SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE to a different install. The override does not cover" >&2
    echo "the LaunchAgent: keep SOLAR_CLIENT_LAUNCHCTL on a test double as well." >&2
    return 97
  fi
  return 0
}

solar_test_guard() {
  local live resolved lc check_services=0 arg
  for arg in "$@"; do
    case "$arg" in
      --services) check_services=1 ;;
      *) echo "ABORT: solar_test_guard: unknown argument ($arg)." >&2; exit 97 ;;
    esac
  done
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
  if [[ "$check_services" -eq 1 ]]; then
    solar_test_guard_services || exit 97
  fi
  return 0
}
