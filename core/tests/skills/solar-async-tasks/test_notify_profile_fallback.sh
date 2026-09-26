#!/usr/bin/env bash
# Notify without origin_chat_id must still find the chat id in the user's
# profile under sun/preferences/.
#
# Regression guard: the queue moved out of the workspace, so notify can no
# longer climb out of $SOLAR_TASK_ROOT to find sun/. If that climb is dropped
# without replacing it, the profile fallback silently stops firing — the task
# is simply never announced, with no error anywhere.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
NOTIFY="$CORE_ROOT/skills/solar-async-tasks/scripts/notify_if_configured.sh"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Machine state outside the workspace, in a temporary app-data dir.
export SOLAR_APP_DATA="$TMP/AppData"
export SOLAR_WORKSPACE="$TMP/ws"
export SOLAR_ROOT="$SOLAR_WORKSPACE"
unset SOLAR_TASK_ROOT
mkdir -p "$SOLAR_WORKSPACE/sun/preferences" \
         "$SOLAR_WORKSPACE/core/skills/solar-telegram/scripts" \
         "$SOLAR_APP_DATA/Solar/runtime/async-tasks/completed"

# The queue must resolve to the runtime root, not to the workspace.
RESOLVED_ROOT="$(bash -c 'source "$0/skills/solar-async-tasks/scripts/task_lib.sh" >/dev/null 2>&1; printf "%s" "$SOLAR_TASK_ROOT"' "$CORE_ROOT")"
# The resolver canonicalises, so compare against the resolved app-data path.
EXPECTED_ROOT="$(cd "$SOLAR_APP_DATA" && pwd -P)/Solar/runtime/async-tasks"
if [[ "$RESOLVED_ROOT" == "$EXPECTED_ROOT" ]]; then
  pass "task root resolves to the runtime root, not to sun/"
else
  fail "task root resolves to the runtime root, not to sun/ (got: $RESOLVED_ROOT)"
fi

cat >"$SOLAR_WORKSPACE/sun/preferences/profile.md" <<'PROFILE'
# Profile

- telegram_chat_id: "777"
PROFILE

cat >"$SOLAR_WORKSPACE/core/skills/solar-telegram/scripts/send_telegram.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "chat=${TELEGRAM_CHAT_ID}" >>"${SOLAR_WORKSPACE}/notify.log"
echo "msg=${1:-}" >>"${SOLAR_WORKSPACE}/notify.log"
STUB
chmod +x "$SOLAR_WORKSPACE/core/skills/solar-telegram/scripts/send_telegram.sh"

TASK_FILE="$SOLAR_APP_DATA/Solar/runtime/async-tasks/completed/profile-fallback.md"
cat >"$TASK_FILE" <<'TASK'
---
id: profile-fallback
title: Profile fallback task
status: completed
notify_when: completed
---

# Profile fallback task

## Result
Done.
TASK

export TELEGRAM_BOT_TOKEN="t"
export TELEGRAM_ALLOWED_CHAT_IDS="777"
# The point of the test: no origin_chat_id on the task, and no default in env.
unset TELEGRAM_CHAT_ID
: >"$SOLAR_WORKSPACE/notify.log"

python3 - <<PY
import sys
sys.path.insert(0, "$CORE_ROOT/skills/solar-state/scripts")
import solar_state
with solar_state.cutover() as cut:
    cut.upgrade_schema()
    cut.set_format("sqlite")
with open("$TASK_FILE", encoding="utf-8") as handle:
    text = handle.read()
with solar_state.session() as store:
    store.task_import(text, status="completed", source_name="profile-fallback")
PY

bash "$NOTIFY" "profile-fallback"

if grep -q 'chat=777' "$SOLAR_WORKSPACE/notify.log"; then
  pass "notify falls back to telegram_chat_id in sun/preferences/profile.md"
else
  fail "notify falls back to telegram_chat_id in sun/preferences/profile.md"
  echo "  notify.log:" >&2
  sed 's/^/    /' "$SOLAR_WORKSPACE/notify.log" >&2
fi

if python3 "$CORE_ROOT/skills/solar-state/scripts/solar_state.py" task show profile-fallback | grep -q 'notify_delivered: true'; then
  pass "task is marked notify_delivered"
else
  fail "task is marked notify_delivered"
fi

# Nothing may have been written inside the workspace queue.
if [[ ! -d "$SOLAR_WORKSPACE/sun/runtime" ]]; then
  pass "no queue was created inside sun/"
else
  fail "no queue was created inside sun/"
fi

echo "=== $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]]
