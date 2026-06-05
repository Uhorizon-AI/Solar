#!/usr/bin/env bash
# test_host_env_compat.sh — SOLAR_APP_PORT=9000 honored; legacy env aliases work.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
HOST_LIB="$SCRIPTS/host_lib.sh"
PASS=0
FAIL=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi

export SOLAR_APP_DATA="$TMP/appdata"
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/.solar"
echo '{"layout":"solar-client-v1.1"}' >"$WS/.solar/manifest.json"
WS="$(cd "$WS" && pwd -P)"

python3 "$SCRIPTS/host_registry.py" add "$WS" "env-test"
python3 "$SCRIPTS/host_registry.py" use "$WS"

assert_port() {
  local label="$1"
  local expected="$2"
  (
    cd "$WS"
    # shellcheck source=/dev/null
    source "$HOST_LIB"
    solar_host_load_env
    if [[ "${SOLAR_APP_PORT}" == "$expected" ]]; then
      echo "PASS: $label (port=$expected)"
      exit 0
    fi
    echo "FAIL: $label expected $expected got ${SOLAR_APP_PORT} (ws=$SOLAR_WORKSPACE)" >&2
    exit 1
  ) && PASS=$((PASS + 1)) || FAIL=$((FAIL + 1))
}

echo "SOLAR_APP_PORT=9000" >"$WS/.env"
assert_port "explicit SOLAR_APP_PORT=9000" "9000"

echo "SOLAR_HOST_PORT=8801" >"$WS/.env"
assert_port "legacy SOLAR_HOST_PORT" "8801"

echo "SOLAR_INTERFACE_PORT=8802" >"$WS/.env"
assert_port "legacy SOLAR_INTERFACE_PORT" "8802"

: >"$WS/.env"
HASH_PORT="$(python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import host_registry as r; print(r.port_offsets('$WS')[0])")"
(
  cd "$WS"
  # shellcheck source=/dev/null
  source "$HOST_LIB"
  solar_host_load_env
  if [[ "${SOLAR_APP_PORT}" == "$HASH_PORT" ]]; then
    echo "PASS: unset port uses workspace hash ($HASH_PORT)"
    exit 0
  fi
  echo "FAIL: unset port expected hash $HASH_PORT got ${SOLAR_APP_PORT}" >&2
  exit 1
) && PASS=$((PASS + 1)) || FAIL=$((FAIL + 1))

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
