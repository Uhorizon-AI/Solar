#!/usr/bin/env bash
# Voice CLI intents against Host fixture — no whisper/rec.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
IFACE_SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
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
export SOLAR_APP_PORT=19007
export SOLAR_APP_HOST=127.0.0.1
export SOLAR_APP_BASE_URL="http://127.0.0.1:${SOLAR_APP_PORT}"
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun"
WS="$(cd "$WS" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

python3 "$SCRIPTS/host_registry.py" add "$WS" "voice-cli"

python3 - <<'PY' "$IFACE_SCRIPTS" "$WS" || exit 1
import sqlite3
import sys
from pathlib import Path

iface_scripts = Path(sys.argv[1])
ws = sys.argv[2]
sys.path.insert(0, str(iface_scripts))

from interface_store import InterfaceStore

store = InterfaceStore(ws)
store.ensure_runtime()
conn = store.connect_db()
conn.execute(
    """
    INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, started_at)
    VALUES ('run_voice1', 'req_voice1', 'thread_voice1', 'awaiting_approval', 'auto', '2026-01-01T00:00:00+00:00')
    """
)
conn.execute(
    """
    INSERT INTO approvals(approval_id, run_id, status, reason, requested_at)
    VALUES ('appr_voice1', 'run_voice1', 'pending', 'voice test', '2026-01-01T00:00:00+00:00')
    """
)
conn.commit()
conn.close()
print("OK: seeded approval")
PY

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

assert_ok "host health" curl -sf "http://127.0.0.1:${SOLAR_APP_PORT}/health" >/dev/null

export SOLAR_VOICE_TTS=off
export SOLAR_VOICE_TEXT="status"
assert_ok "voice command status" bash -c "python3 '$SCRIPTS/voice_cli.py' command | grep -q 'workspace'"

export SOLAR_VOICE_TEXT="approve"
assert_ok "voice command approve" bash -c "python3 '$SCRIPTS/voice_cli.py' command; curl -sf 'http://127.0.0.1:${SOLAR_APP_PORT}/api/approvals' | python3 -c \"import json,sys; d=json.load(sys.stdin); a=next(x for x in d['approvals'] if x['approval_id']=='appr_voice1'); assert a['status']!='pending'\""

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
