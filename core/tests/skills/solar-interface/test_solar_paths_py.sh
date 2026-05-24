#!/usr/bin/env bash
# Anti-contamination: solar_paths.py must not trust stale SOLAR_HOME without discovery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WS_A="$TMP/workspace-a"
WS_B="$TMP/workspace-b"
mkdir -p "$WS_A/.solar/core/skills" "$WS_A/sun"
mkdir -p "$WS_B/.solar/core/skills" "$WS_B/sun"

export SOLAR_HOME="$WS_A"
export SOLAR_CORE_ROOT="$WS_A/.solar/core"
export REPO_ROOT="$WS_A"

if ! (cd "$WS_B" && python3 "$ROOT/core/skills/solar-interface/scripts/solar_paths.py" 2>/dev/null); then
  echo "PASS: solar_paths.py fails on workspace conflict"
  exit 0
fi

resolved="$(cd "$WS_B" && python3 "$ROOT/core/skills/solar-interface/scripts/solar_paths.py" 2>/dev/null | head -1 || true)"
if [[ "$resolved" == SOLAR_HOME="$WS_B"* ]] || [[ "$resolved" == SOLAR_HOME="$(cd "$WS_B" && pwd -P)"* ]]; then
  echo "PASS: solar_paths.py resolves workspace B from cwd"
  exit 0
fi

echo "FAIL: solar_paths.py kept stale SOLAR_HOME (got: $resolved)" >&2
exit 1
