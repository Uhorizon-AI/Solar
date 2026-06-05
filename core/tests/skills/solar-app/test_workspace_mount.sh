#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
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

WS_A="$TMP/ws-a"
WS_B="$TMP/ws-b"
mkdir -p "$WS_A/sun" "$WS_B/sun"
printf '%s\n' "SOLAR_APP_PORT=8801" "CUSTOM_KEY=from_a" >"$WS_A/.env"
echo "SOLAR_APP_PORT=8802" >"$WS_B/.env"
WS_A="$(cd "$WS_A" && pwd -P)"
WS_B="$(cd "$WS_B" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ -d "${SOLAR_ROOT}/core" ]]; then
  :
else
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi

MOUNT_EXIT=0
python3 - <<'PY' "$SCRIPTS" "$WS_A" "$WS_B" || MOUNT_EXIT=$?
import os
import sys
from pathlib import Path

scripts = Path(sys.argv[1])
ws_a = sys.argv[2]
ws_b = sys.argv[3]
sys.path.insert(0, str(scripts))

import host_registry as reg
import host_workspace_context as ctx
import host_interface as hi

reg.add_workspace(ws_a, "a")
reg.add_workspace(ws_b, "b")

ctx.switch_workspace(ws_a)
db_a = ctx.legacy_interface_db_path(ws_a)
mounted = ctx.get_mounted()
assert mounted == ws_a, (mounted, ws_a)
assert db_a == Path(ws_a) / "sun/runtime/app/db/interface.sqlite"
assert db_a.parent.is_dir(), "runtime db dir should exist"

store_a = hi.get_store(ws_a)
ready_a, _ = store_a.readiness()
assert ready_a, "store should be ready after mount"

ctx.switch_workspace(ws_b)
db_b = ctx.legacy_interface_db_path(ws_b)
assert ctx.get_mounted() == ws_b
assert db_a != db_b
assert os.environ.get("SOLAR_APP_PORT") == "8802", os.environ.get("SOLAR_APP_PORT")
assert os.environ.get("CUSTOM_KEY") is None, os.environ.get("CUSTOM_KEY")

store_b = hi.get_store(ws_b)
assert store_b.workspace == Path(ws_b)
assert store_b is not store_a

print("OK: mount/switch/in-process store")
PY

assert_ok "python mount/switch unit" test "$MOUNT_EXIT" -eq 0

# Static: host_server should not proxy approvals in default (non-legacy) path
assert_ok "host_server uses in-process store" bash -c "grep -q '_active_store' '$SCRIPTS/host_server.py' && grep -q 'store.list_approvals' '$SCRIPTS/host_server.py'"

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
