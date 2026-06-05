#!/usr/bin/env bash
# Host-3: GET /api/governance/tree — fixture workspace; path allowlist + traversal guard.
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
trap 'kill $HOST_PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

export SOLAR_APP_DATA="$TMP/appdata"
export SOLAR_HOST_OFFLINE=1
export SOLAR_APP_PORT=19008
export SOLAR_APP_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/planets/foo" "$WS/.solar"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' >"$WS/.solar/manifest.json"
echo "# memory" >"$WS/sun/MEMORY.md"
echo "# agents" >"$WS/planets/foo/AGENTS.md"
echo '{"k":1}' >"$WS/planets/foo/config.json"
echo "skip me" >"$WS/sun/notes.txt"
WS="$(cd "$WS" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

python3 "$SCRIPTS/host_registry.py" add "$WS" "gov-tree"

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

BASE="http://127.0.0.1:${SOLAR_APP_PORT}"
assert_ok "host health" curl -sf "${BASE}/health" >/dev/null

TREE_JSON="$(curl -sf "${BASE}/api/governance/tree")"
assert_ok "tree HTTP contract" bash -c '
python3 - "$1" <<'"'"'PY'"'"'
import json, sys
d = json.loads(sys.argv[1])
paths = d.get("paths")
if not isinstance(paths, list):
    raise SystemExit("paths missing")
for p in paths:
    if ".." in p or not (p.startswith("sun/") or p.startswith("planets/")):
        raise SystemExit("bad path: " + p)
want = {"sun/MEMORY.md", "planets/foo/AGENTS.md", "planets/foo/config.json"}
have = set(paths)
missing = want - have
if missing:
    raise SystemExit("missing: " + ", ".join(sorted(missing)))
if "sun/notes.txt" in have:
    raise SystemExit("txt must not appear in tree")
PY
' _ "$TREE_JSON"

BAD_CODE="$(curl -s -o /tmp/gov_bad.txt -w '%{http_code}' \
  "${BASE}/api/governance/file?path=..%2F..%2Fetc%2Fpasswd")"
assert_ok "reject traversal on file GET" test "$BAD_CODE" = "404"

assert_ok "registry rejects traversal" python3 <<PY
import sys
sys.path.insert(0, "$SCRIPTS")
import host_registry as reg
assert reg.governance_resolve("$WS", "../etc/passwd") is None
assert reg.governance_resolve("$WS", "planets/foo/AGENTS.md") is not None
tree = reg.governance_tree("$WS")
assert "sun/MEMORY.md" in tree
assert "sun/notes.txt" not in tree
PY

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
