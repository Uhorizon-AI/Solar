#!/usr/bin/env bash
# The LaunchAgent stamp is written on a temporary runtime, atomically.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
WRITER="$CORE_ROOT/skills/solar-system/scripts/write_pass_stamp.sh"
ORCH="$CORE_ROOT/skills/solar-system/scripts/run_orchestrator.sh"
# shellcheck source=../../../support/shell_runtime_guard.sh
source "$CORE_ROOT/tests/support/shell_runtime_guard.sh"

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
mkdir -p "$TMP/runtime"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$TMP/launchctl"
chmod +x "$TMP/launchctl"
export SOLAR_RUNTIME_ROOT="$TMP/runtime"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/launchctl"
unset SOLAR_APP_DATA
solar_test_guard

GW='{"processes":{"ws":true,"http":false,"tunnel":true},"local_health":true,"connector_ready":false}'
bash "$WRITER" --feature async-tasks=ok --feature transport-gateway=failed --gateway-json "$GW"
STAMP="$SOLAR_RUNTIME_ROOT/system/pass-stamp.json"
assert_ok "stamp file exists" test -f "$STAMP"
assert_ok "no partial stamp remains" bash -c '! compgen -G "$1/system/.pass-stamp.*" >/dev/null' _ "$SOLAR_RUNTIME_ROOT"
python3 - "$STAMP" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["features"] == {"async-tasks": "ok", "transport-gateway": "failed"}
assert data["gateway"]["connector_ready"] is False
assert data["gateway"]["processes"]["ws"] is True
assert "T" in data["at"] and data["at"].endswith("Z")
print("PASS: stamp json")
PY
PASS=$((PASS + 1))

first="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["at"])' "$STAMP")"
sleep 1
GW2='{"processes":{"ws":true,"http":true,"tunnel":true},"local_health":true,"connector_ready":true}'
bash "$WRITER" --feature host=ok --gateway-json "$GW2"
second="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["at"])' "$STAMP")"
assert_ok "a second pass replaces the stamp" test "$first" != "$second"
python3 - "$STAMP" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["features"] == {"host": "ok"}
assert data["gateway"]["connector_ready"] is True
print("PASS: replaced stamp")
PY
PASS=$((PASS + 1))
assert_ok "orchestrator writes the stamp" grep -q 'write_pass_stamp.sh' "$ORCH"

echo "$PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
