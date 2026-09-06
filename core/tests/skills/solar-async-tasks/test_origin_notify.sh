#!/usr/bin/env bash
# Origin metadata and notify_when on queued tasks; origin notify allowlist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CREATE="$CORE_ROOT/skills/solar-async-tasks/scripts/create.sh"
NOTIFY="$CORE_ROOT/skills/solar-async-tasks/scripts/notify_if_configured.sh"
TASK_LIB="$CORE_ROOT/skills/solar-async-tasks/scripts/task_lib.sh"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export SOLAR_WORKSPACE="$TMP/ws"
export SOLAR_TASK_ROOT="$SOLAR_WORKSPACE/sun/runtime/async-tasks"
export SOLAR_ROOT="$SOLAR_WORKSPACE"
mkdir -p "$SOLAR_WORKSPACE/sun/runtime/async-tasks" "$SOLAR_WORKSPACE/core/skills/solar-telegram/scripts"
# shellcheck source=/dev/null
source "$TASK_LIB"
ensure_dirs

OUT="$(bash "$CREATE" --queued --scheduled-time now \
  --metadata '{"origin_channel":"telegram","origin_chat_id":"456","origin_request_id":"tg:1"}' \
  "Origin Task" "Do the thing")"
ID="$(printf '%s' "$OUT" | awk '/^ID:/{print $2}')"
FILE="$(find_task "$ID")"
if [[ -n "$FILE" ]] && grep -q 'origin_chat_id: "456"' "$FILE" \
  && grep -q 'origin_request_id: "tg:1"' "$FILE" \
  && grep -q 'origin_channel: "telegram"' "$FILE" \
  && grep -q 'notify_when: completed' "$FILE"; then
  pass "create.sh --metadata writes origin_* and notify_when"
else
  fail "create.sh --metadata writes origin_* and notify_when"
  echo "$OUT" | sed 's/^/  /' >&2
  [[ -n "${FILE:-}" ]] && sed 's/^/  /' "$FILE" >&2
fi

OUT_NESTED="$(bash "$CREATE" --queued --scheduled-time now \
  --metadata '{"origin":{"channel":"telegram","chat_id":"789","request_id":"tg:2"}}' \
  "Nested Origin" "Do the nested thing")"
ID_NESTED="$(printf '%s' "$OUT_NESTED" | awk '/^ID:/{print $2}')"
FILE_NESTED="$(find_task "$ID_NESTED")"
if [[ -n "$FILE_NESTED" ]] && grep -q 'origin_chat_id: "789"' "$FILE_NESTED" \
  && grep -q 'origin_request_id: "tg:2"' "$FILE_NESTED" \
  && grep -q 'origin_channel: "telegram"' "$FILE_NESTED" \
  && grep -q 'notify_when: completed' "$FILE_NESTED"; then
  pass "create.sh --metadata accepts nested origin"
else
  fail "create.sh --metadata accepts nested origin"
  echo "$OUT_NESTED" | sed 's/^/  /' >&2
  [[ -n "${FILE_NESTED:-}" ]] && sed 's/^/  /' "$FILE_NESTED" >&2
fi

OUT_CHILD="$(bash "$CREATE" --queued --scheduled-time now \
  "Child Task" "No origin")"
ID_CHILD="$(printf '%s' "$OUT_CHILD" | awk '/^ID:/{print $2}')"
FILE_CHILD="$(find_task "$ID_CHILD")"
if [[ -n "$FILE_CHILD" ]] && ! grep -q 'notify_when:' "$FILE_CHILD" \
  && ! grep -q 'origin_chat_id:' "$FILE_CHILD"; then
  pass "create.sh --queued without --metadata has no notify_when"
else
  fail "create.sh --queued without --metadata has no notify_when"
  echo "$OUT_CHILD" | sed 's/^/  /' >&2
  [[ -n "${FILE_CHILD:-}" ]] && sed 's/^/  /' "$FILE_CHILD" >&2
fi

if ! bash "$CREATE" --queued --origin-channel telegram "Old Flags" "nope" >/dev/null 2>&1; then
  pass "create.sh rejects --origin-channel"
else
  fail "create.sh rejects --origin-channel"
fi

# Stub send_telegram: record chat_id and message
cat >"$SOLAR_WORKSPACE/core/skills/solar-telegram/scripts/send_telegram.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname "$0")/../../../.."
echo "chat=${TELEGRAM_CHAT_ID}" >>"${SOLAR_WORKSPACE}/notify.log"
echo "msg=${1:-}" >>"${SOLAR_WORKSPACE}/notify.log"
STUB
# The stub path is relative to SOLAR_ROOT used by notify (= dirname of sun)
# notify resolves SOLAR_ROOT from SOLAR_TASK_ROOT: sun/runtime/async-tasks -> workspace
chmod +x "$SOLAR_WORKSPACE/core/skills/solar-telegram/scripts/send_telegram.sh"

export TELEGRAM_BOT_TOKEN="t"
export TELEGRAM_CHAT_ID="111"
export TELEGRAM_ALLOWED_CHAT_IDS="456,789"
: >"$SOLAR_WORKSPACE/notify.log"
bash "$NOTIFY" "$FILE"
if grep -q 'chat=456' "$SOLAR_WORKSPACE/notify.log" \
  && grep -q 'Tarea completada' "$SOLAR_WORKSPACE/notify.log" \
  && grep -q 'notify_delivered: true' "$FILE"; then
  pass "notify sends to origin_chat_id and marks notify_delivered"
else
  fail "notify sends to origin_chat_id and marks notify_delivered"
  sed 's/^/  /' "$SOLAR_WORKSPACE/notify.log" >&2
  sed 's/^/  /' "$FILE" >&2
fi

: >"$SOLAR_WORKSPACE/notify.log"
bash "$NOTIFY" "$FILE"
if [[ ! -s "$SOLAR_WORKSPACE/notify.log" ]]; then
  pass "notify does not re-send after notify_delivered"
else
  fail "notify does not re-send after notify_delivered"
fi

UNAUTHORIZED="$DIR_COMPLETED/unauth.md"
cat >"$UNAUTHORIZED" <<'EOF'
---
id: "unauth-1"
title: "Nope"
status: completed
notify_when: completed
origin_chat_id: "999"
---
# Nope
EOF
: >"$SOLAR_WORKSPACE/notify.log"
bash "$NOTIFY" "$UNAUTHORIZED"
if [[ ! -s "$SOLAR_WORKSPACE/notify.log" ]]; then
  pass "notify skips chat not on allowlist"
else
  fail "notify skips chat not on allowlist"
fi

: >"$SOLAR_WORKSPACE/notify.log"
bash "$NOTIFY" "$FILE_CHILD"
if [[ ! -s "$SOLAR_WORKSPACE/notify.log" ]]; then
  pass "notify skips child without notify_when"
else
  fail "notify skips child without notify_when"
fi

echo ""
echo "Results: PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
