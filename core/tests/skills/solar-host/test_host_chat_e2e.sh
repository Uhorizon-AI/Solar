#!/usr/bin/env bash
# Host-3: POST /api/chat happy path — mock router via SOLAR_ROUTER_CLAUDE_CMD (not voice mock).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
IFACE_SCRIPTS="$CORE_ROOT/skills/solar-interface/scripts"
ROUTER_SCRIPTS="$CORE_ROOT/skills/solar-router/scripts"
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
export SOLAR_HOST_PORT=19007
export SOLAR_HOST_HOST=127.0.0.1
mkdir -p "$SOLAR_APP_DATA"

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/.solar"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' >"$WS/.solar/manifest.json"
WS="$(cd "$WS" && pwd -P)"

export SOLAR_ROOT="$CORE_ROOT/.."
if [[ ! -d "${SOLAR_ROOT}/core" ]]; then
  SOLAR_ROOT="$(cd "$CORE_ROOT" && pwd)"
fi
export SOLAR_WORKSPACE="$WS"

MOCK_ROUTER="$TMP/mock_router_reply.sh"
cat >"$MOCK_ROUTER" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' '{"status":"success","reply_text":"host chat mock reply","provider_used":"claude"}'
MOCK
chmod +x "$MOCK_ROUTER"

cat >>"$WS/.env" <<ENV
SOLAR_ROOT=$SOLAR_ROOT
SOLAR_ROUTER_PROVIDER_PRIORITY=claude
SOLAR_ROUTER_CLAUDE_CMD=bash $MOCK_ROUTER
ENV

python3 "$SCRIPTS/host_registry.py" add "$WS" "chat-e2e"

python3 "$SCRIPTS/host_server.py" &
HOST_PID=$!
sleep 2

BASE="http://127.0.0.1:${SOLAR_HOST_PORT}"
assert_ok "host health" curl -sf "${BASE}/health" >/dev/null

CHAT_CODE="$(curl -s -o /tmp/chat_out.json -w '%{http_code}' -X POST "${BASE}/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"hello host chat"}')"
assert_ok "chat HTTP 200" test "$CHAT_CODE" = "200"

assert_ok "chat contract" python3 <<'PY'
import json
import sys

d = json.load(open("/tmp/chat_out.json"))
reply = (d.get("reply_text") or "").strip()
run = d.get("run") or {}
if run.get("status") != "succeeded":
    print("run:", run, file=sys.stderr)
    print("router:", d.get("router"), file=sys.stderr)
    sys.exit(1)
if not reply:
    print("empty reply_text", file=sys.stderr)
    sys.exit(1)
if "host chat mock reply" not in reply:
    print("unexpected reply:", reply, file=sys.stderr)
    sys.exit(1)
PY

kill "$HOST_PID" 2>/dev/null || true
wait "$HOST_PID" 2>/dev/null || true
HOST_PID=""

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
