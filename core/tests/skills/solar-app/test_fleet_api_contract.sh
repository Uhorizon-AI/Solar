#!/usr/bin/env bash
# MVP-b b4: port_offsets not exposed in public list_workspaces API shape.
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
mkdir -p "$SOLAR_APP_DATA" "$TMP/ws/sun"
WS="$(cd "$TMP/ws" && pwd -P)"

python3 "$REGISTRY_PY" add "$WS" "one"
LIST="$(python3 "$REGISTRY_PY" list)"

assert_ok "list has interface_base" bash -c "echo '$LIST' | grep -q 'interface_base'"
assert_ok "list omits interface_port" bash -c "! echo '$LIST' | grep -q 'interface_port'"
assert_ok "ports CLI still works (deprecated internal)" bash -c "test \$(python3 \"$REGISTRY_PY\" ports \"$WS\" | wc -w) -eq 2"

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
