#!/usr/bin/env bash
# The console port is no longer written to .env: the doctor must assume 9000 and must
# not abort (set -e) when SOLAR_APP_PORT is unset and SOLAR_HTTP_PORT has no listener.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPTS="$ROOT/skills/solar-client/scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
unset SOLAR_APP_PORT SOLAR_HTTP_PORT
export SOLAR_APP_DATA="$TMP/appdata" SOLAR_RUNTIME_ROOT="$TMP/runtime"

out="$(bash -c '
  set -euo pipefail
  source "$1/client_lib.sh"
  source "$1/client_doctor_lib.sh"
  solar_client_check_ports || true
  echo reached-end
' _ "$SCRIPTS" 2>&1)" || { echo "FAIL: solar_client_check_ports aborted: $out"; exit 1; }
grep -q reached-end <<<"$out" || { echo "FAIL: did not reach the end: $out"; exit 1; }

# And the verbose check in client_doctor.sh: extract the function and run it under set -e.
out="$(bash -c '
  set -euo pipefail
  ok() { echo "OK: $1"; }; warn() { echo "WARN: $1"; }
  source "$1/client_lib.sh"
  source "$1/client_doctor_lib.sh"
  eval "$(sed -n "/^_port_check_verbose() {/,/^}/p" "$1/client_doctor.sh")"
  _port_check_verbose SOLAR_APP_PORT
  _port_check_verbose SOLAR_HTTP_PORT
  echo reached-end
' _ "$SCRIPTS" 2>&1)" || { echo "FAIL: _port_check_verbose aborted: $out"; exit 1; }
grep -q reached-end <<<"$out" || { echo "FAIL: verbose check did not reach the end: $out"; exit 1; }
echo "PASS: doctor port checks survive an unset SOLAR_APP_PORT and no HTTP listener"
