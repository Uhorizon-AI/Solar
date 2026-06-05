#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
REGISTRY_PY="$CORE_ROOT/skills/solar-app/scripts/host_registry.py"
PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export SOLAR_APP_DATA="$TMP/appdata"
export SOLAR_HOST_OFFLINE=1
mkdir -p "$SOLAR_APP_DATA"
mkdir -p "$TMP/ws1/sun" "$TMP/ws2/sun"
WS1="$(cd "$TMP/ws1" && pwd -P)"
WS2="$(cd "$TMP/ws2" && pwd -P)"

REGISTRY_FILE="$SOLAR_APP_DATA/Solar/workspaces.json"

python3 "$REGISTRY_PY" add "$WS1" "one"
python3 "$REGISTRY_PY" add "$WS2" "two"
python3 "$REGISTRY_PY" use "$WS2"
active="$(python3 "$REGISTRY_PY" active)"
assert_ok "active is ws2" test "$active" = "$WS2"

assert_ok "registry under SOLAR_APP_DATA" test -f "$REGISTRY_FILE"

list="$(python3 "$REGISTRY_PY" list)"
assert_ok "list contains two workspaces" bash -c "echo '$list' | grep -q '$WS1' && echo '$list' | grep -q '$WS2'"

ports="$(python3 "$REGISTRY_PY" ports "$WS1")"
assert_ok "ports returns two numbers" bash -c "test $(echo \"$ports\" | wc -w) -eq 2"

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
