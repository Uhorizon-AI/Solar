#!/usr/bin/env bash
# A completed task still reaches Telegram after the token left the workspace.
#
# `notify_if_configured.sh` is the Solar runtime, so it is one of the processes
# allowed to open the installation secret store. The workspace `.env` keeps the
# chat id and nothing else.
#
# Fixtures only: a temp workspace, a temp store and a stub sender. Nothing is
# sent and the machine's real store is never read.
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
mkdir -p "$SOLAR_WORKSPACE/sun/runtime/async-tasks"

# A root that carries the real secret loader and a stub sender, so the test
# exercises the real lookup without a real send.
FAKE_ROOT="$TMP/root"
mkdir -p "$FAKE_ROOT/core/skills" "$FAKE_ROOT/core/skills/solar-telegram/scripts"
ln -s "$CORE_ROOT/skills/solar-client" "$FAKE_ROOT/core/skills/solar-client"
cat >"$FAKE_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
# Record what the runtime handed over. A real sender would need exactly this.
echo "token=${TELEGRAM_BOT_TOKEN:-<none>}" >>"${SOLAR_WORKSPACE}/notify.log"
echo "chat=${TELEGRAM_CHAT_ID:-<none>}" >>"${SOLAR_WORKSPACE}/notify.log"
STUB
chmod +x "$FAKE_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh"
export SOLAR_ROOT="$FAKE_ROOT"

# The workspace: visible configuration, no token. This is the point of the corte.
cat >"$SOLAR_WORKSPACE/.env" <<'EOF'
# [solar-telegram] required environment
TELEGRAM_CHAT_ID=111
EOF

STORE="$TMP/app-data/Solar/secrets/installation.env"
mkdir -p "$(dirname "$STORE")"
echo "TELEGRAM_BOT_TOKEN=token-from-the-process" >"$STORE"
chmod 600 "$STORE"
export SOLAR_SECRETS_FILE="$STORE"

# shellcheck source=/dev/null
source "$TASK_LIB"
ensure_dirs

OUT="$(bash "$CREATE" --queued --scheduled-time now \
  --metadata '{"origin_channel":"telegram","origin_chat_id":"111","origin_request_id":"tg:1"}' \
  "Tarea con aviso" "Do the thing")"
ID="$(printf '%s' "$OUT" | awk '/^ID:/{print $2}')"
FILE="$(find_task "$ID")"

: >"$SOLAR_WORKSPACE/notify.log"
bash "$NOTIFY" "$FILE"

if grep -q 'token=token-from-the-process' "$SOLAR_WORKSPACE/notify.log"; then
  pass "notify hands the sender the token from the process store"
else
  fail "notify hands the sender the token from the process store"
  sed 's/^/  /' "$SOLAR_WORKSPACE/notify.log" >&2
fi

if grep -q 'chat=111' "$SOLAR_WORKSPACE/notify.log" \
  && grep -q 'notify_delivered: true' "$FILE"; then
  pass "the chat id still comes from the workspace"
else
  fail "the chat id still comes from the workspace"
  sed 's/^/  /' "$SOLAR_WORKSPACE/notify.log" >&2
fi

# Without a store there is no token, and the failure is recorded rather than
# silently swallowed: a notification that did not go out must be visible.
OUT2="$(bash "$CREATE" --queued --scheduled-time now \
  --metadata '{"origin_channel":"telegram","origin_chat_id":"111","origin_request_id":"tg:2"}' \
  "Tarea sin almacen" "Do the other thing")"
ID2="$(printf '%s' "$OUT2" | awk '/^ID:/{print $2}')"
FILE2="$(find_task "$ID2")"

cat >"$FAKE_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || { echo "Missing required key: TELEGRAM_BOT_TOKEN"; exit 1; }
echo "sent" >>"${SOLAR_WORKSPACE}/notify.log"
STUB
chmod +x "$FAKE_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh"

: >"$SOLAR_WORKSPACE/notify.log"
SOLAR_SECRETS_FILE="$TMP/absent.env" bash "$NOTIFY" "$FILE2" >/dev/null 2>&1 || true
if grep -q 'notify_status: failed' "$FILE2" && [[ ! -s "$SOLAR_WORKSPACE/notify.log" ]]; then
  pass "no store means no send, and the task says so"
else
  fail "no store means no send, and the task says so"
  sed 's/^/  /' "$FILE2" >&2
fi

echo ""
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
