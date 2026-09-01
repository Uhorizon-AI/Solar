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

IMPORT_EXIT=0
python3 - <<'PY' "$SCRIPTS" || IMPORT_EXIT=$?
import sys
from pathlib import Path

scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts))

# Simulate another module importing stdlib `platform` first.
import platform as stdlib_platform  # noqa: F401

import host_registry as reg

assert reg.REGISTRY_DIR.name == "Solar"
print("OK: host_registry after stdlib platform")
PY

assert_ok "host_registry imports after stdlib platform" test "$IMPORT_EXIT" -eq 0

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
