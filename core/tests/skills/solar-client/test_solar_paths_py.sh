#!/usr/bin/env bash
# Anti-contamination: solar_paths.py must not trust stale SOLAR_WORKSPACE without discovery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WS_A="$TMP/workspace-a"
WS_B="$TMP/workspace-b"
mkdir -p "$WS_A/.solar" "$WS_A/sun" "$WS_B/.solar" "$WS_B/sun"
echo '{"layout":"solar-client-v1.1"}' > "$WS_A/.solar/manifest.json"
echo '{"layout":"solar-client-v1.1"}' > "$WS_B/.solar/manifest.json"

export SOLAR_WORKSPACE="$(cd "$WS_A" && pwd -P)"

SOLAR_PATHS_PY="$ROOT/core/skills/solar-client/scripts/solar_paths.py"
SHIM_PY="$ROOT/core/skills/solar-interface/scripts/solar_paths.py"

shim_out="$(cd "$WS_A" && python3 "$SHIM_PY" 2>/dev/null || true)"
if ! echo "$shim_out" | grep -q "^SOLAR_WORKSPACE=" || ! echo "$shim_out" | grep -q "^SOLAR_ROOT="; then
  echo "FAIL: interface shim solar_paths.py __main__ must print SOLAR_WORKSPACE and SOLAR_ROOT" >&2
  echo "got: $shim_out" >&2
  exit 1
fi

if ! (cd "$WS_B" && python3 "$SOLAR_PATHS_PY" 2>/dev/null); then
  echo "PASS: solar_paths.py fails on workspace conflict"
  exit 0
fi

resolved="$(cd "$WS_B" && python3 "$SOLAR_PATHS_PY" 2>/dev/null | head -1 || true)"
ws_b="$(cd "$WS_B" && pwd -P)"
if [[ "$resolved" == "SOLAR_WORKSPACE=$ws_b" ]]; then
  echo "PASS: solar_paths.py resolves workspace B from cwd"
  exit 0
fi

echo "FAIL: solar_paths.py kept stale SOLAR_WORKSPACE (got: $resolved)" >&2
exit 1
