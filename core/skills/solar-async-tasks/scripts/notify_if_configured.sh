#!/bin/bash

# If the finished task asks for it in notify_when, send a Telegram notification
# to the allowlisted origin chat (or TELEGRAM_CHAT_ID). notify_when is a comma
# list of `completed`, `delivery` and `failed`. `delivery` (opt-in, quiet) announces a success only when the
# delivery of THIS run is non-empty, and says nothing otherwise. A bare `completed` (older tasks) also reports a failure; only the
# explicit `completed,-failed` that task.create / task.update store for "completion only" does not. The approval-wait notice (--waiting) is sent for every task.
# When the task carries a
# `## Delivery` section, that is the message: the one-screen delivery the
# executor wrote, ending in its own evidence line. Otherwise a brief line plus
# the result location. Long text is chunked (~1s apart).
# Usage: notify_if_configured.sh <task_id> [--waiting|--expired-draft|--expired-skipped]
#
# SOLAR_NOTIFY_EXPECT_RUN / SOLAR_NOTIFY_EXPECT_STATUS (set by every path that announces a failure it just
# recorded: the supervisor, the executor and the cleanup failure of complete.sh):
# the notice belongs to that run, and nothing is sent once the task has been claimed again or has left that status.
# SOLAR_NOTIFY_LOCK_WAIT: seconds to wait for the per-task lock (default 150).
#
# The optional mode announces a task that waits for `task.authorize_run`, or whose wait ended. It goes
# to the configured chat only (never the origin chat a task names), carries the title and no instructions
# (--waiting adds a short task id and the expiry), and does not touch the task.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

TASK_ID="${1:-}"
[[ -z "$TASK_ID" ]] && { [[ -n "${2:-}" ]] && exit 3; exit 0; }
task_status_of "$TASK_ID" >/dev/null 2>&1 || { [[ -n "${2:-}" ]] && exit 3; exit 0; }   # a notice for a task that is gone was not sent

MODE="${2:-}"
case "$MODE" in
  ""|--waiting|--expired-draft|--expired-skipped) ;;
  *) echo "Unknown notification mode: $MODE" >&2; exit 2 ;;
esac

# The delivery may hold `##` headings of its own: it ends only at a heading the runtime writes after it.
# Keep this list equal to solar_state.RUNTIME_SECTIONS without `## Delivery` (a test checks it).
# The LAST exact `## Delivery` is the one the worker recorded: the instructions come before it and cannot be
# trusted to lack that heading, so every new one starts over.
task_delivery() {
  task_body "$1" | awk '
    /^## Delivery$/ { buf = ""; on = 1; next }
    on && /^## (Subtask results|Execution Error|Result)[[:space:]]*$/ { on = 0; next }
    on { buf = buf $0 "\n" }
    END { printf "%s", buf }
  '
}

if [[ -z "$MODE" ]]; then
  NOTIFY_WHEN=$(task_field "$TASK_ID" "notify_when")
  NOTIFY_WHEN="${NOTIFY_WHEN//[[:space:]]/}"
  notify_wants() {
    [[ ",${NOTIFY_WHEN}," == *",$1,"* ]] && return 0
    # A bare `completed` is what tasks queued before notify_when existed carry, and it announced failures.
    # Only the explicit `completed,-failed` (task.create / task.update) leaves a failure silent.
    [[ "$1" == failed && ",${NOTIFY_WHEN}," == *",completed,"* && ",${NOTIFY_WHEN}," != *",-failed,"* ]]
  }
  if [[ "$(task_status_of "$TASK_ID")" == "error" ]]; then
    notify_wants failed || exit 0
  else
    # `delivery` cannot be judged before the locked snapshot: its content is checked there.
    notify_wants completed || notify_wants delivery || exit 0
  fi

  # One notice per run. The run is the id stamped at claim; a notice for an earlier run never silences this one.
  RUN="$(task_field "$TASK_ID" "notify_run")"
  already_delivered() {
    [[ "$(task_field "$TASK_ID" "notify_delivered")" == "true" \
       && "$(task_field "$TASK_ID" "notify_delivered_run")" == "$RUN" ]]
  }
  already_delivered && exit 0

  # The worker and the supervisor can both announce the same end: serialise check -> send -> record.
  # The lock is an flock on a file descriptor this shell keeps open: the kernel releases it when the shell
  # ends, however it ends, and never while the shell lives, so a slow sender is never evicted and a dead
  # one never blocks anyone.
  LOCK_FILE="${TMPDIR:-/tmp}/solar-notify-${TASK_ID//[^A-Za-z0-9_.-]/_}.flock"
  # Keep this wait below Supervisor.FAILURE_NOTIFY_TIMEOUT, with time left to record failure.
  if ! python3 -c 'import fcntl' >/dev/null 2>&1; then
    # Without python3 + fcntl the lock cannot be taken: say so, instead of waiting out the lock and blaming it.
    state task notice "$TASK_ID" --run "$RUN" --error notify_lock_unavailable --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
    echo "Task notification failed: notify_lock_unavailable ($TASK_ID)" >&2
    exit 1
  fi
  if { exec 9>>"$LOCK_FILE"; } 2>/dev/null; then
    for _ in $(seq 1 "${SOLAR_NOTIFY_LOCK_WAIT:-150}"); do
      python3 -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)' 2>/dev/null && { HAVE_LOCK=1; break; }
      sleep 1
    done
  fi
  if [[ -z "${HAVE_LOCK:-}" ]]; then
    state task notice "$TASK_ID" --run "$RUN" --error notify_lock_timeout --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
    echo "Task notification failed: notify_lock_timeout ($TASK_ID)" >&2
    exit 1
  fi

  # One read of the task, taken with the lock held. Status, run, delivery, title, chat and the failure code
  # all come from it, so a claim that lands later cannot mix two attempts into one message.
  SNAPSHOT="$(state task snapshot "$TASK_ID" 2>/dev/null)" || {
    # The read failed: leave a trace that this notice was lost, instead of exiting without a word.
    state task notice "$TASK_ID" --run "$RUN" --error notify_snapshot_failed --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1
    echo "Task notification failed: notify_snapshot_failed ($TASK_ID)" >&2
    exit 1
  }
  snap() {
    printf '%s' "$SNAPSHOT" | python3 -c 'import json,sys
d=json.load(sys.stdin); w=sys.argv[1]
if w=="status": print(d["status"])
elif w=="body": sys.stdout.write(d.get("body") or "")
else:
    v=d["fields"].get(sys.argv[2]); print("" if v is None else v)' "$@"
  }
  task_status_of() { snap status; }
  task_field() { snap field "$2"; }
  task_body() { snap body; }
  RUN="$(task_field "$TASK_ID" "notify_run")"          # the run of THIS snapshot; every later check is against it
  # A failure the supervisor declared belongs to its run: a task claimed again meanwhile gets no stale notice.
  if [[ -n "${SOLAR_NOTIFY_EXPECT_STATUS:-}" ]]; then
    if [[ -z "${SOLAR_NOTIFY_EXPECT_RUN:-}" && -n "$RUN" ]]; then
      # Without the caller's run, the snapshot may belong to a different attempt.
      echo "Task notification failed: notify_expect_run_missing ($TASK_ID)" >&2
      exit 1
    fi
    [[ "$(task_status_of "$TASK_ID")" == "$SOLAR_NOTIFY_EXPECT_STATUS" \
       && "$RUN" == "${SOLAR_NOTIFY_EXPECT_RUN:-}" ]] || exit 0
  fi
  already_delivered && exit 0
  SNAPSHOT_STATUS="$(task_status_of "$TASK_ID")"       # the last look before sending must still find this status
  # What the snapshot says is what is announced: the status may have moved since the first, unlocked look.
  NOTIFY_WHEN="$(task_field "$TASK_ID" "notify_when")"; NOTIFY_WHEN="${NOTIFY_WHEN//[[:space:]]/}"
  if [[ "$(task_status_of "$TASK_ID")" == "error" ]]; then
    notify_wants failed || exit 0
  elif ! notify_wants completed; then
    # Delivery only: this run's own delivery or nothing. The worker clears the section when a run has none.
    notify_wants delivery || exit 0
    # Only a delivery the executor recorded for this attempt counts: a `## Delivery` heading that came from
    # task text or an import carries no `delivery_recorded`, and sends nothing.
    [[ "$(task_field "$TASK_ID" "delivery_recorded")" == "true" ]] || exit 0
    [[ -n "$(task_delivery "$TASK_ID" | sed -e '/./,$!d')" ]] || exit 0
  fi
fi

TITLE=$(task_field "$TASK_ID" "title")
[[ -z "$TITLE" ]] && TITLE="Task"

# The task root is machine state outside the workspace: never climb out of it
# to find the workspace, its .env or the user's profile. Both come from the
# workspace itself.
WORKSPACE_DIR="${SOLAR_WORKSPACE:-$(cd "$SCRIPT_DIR/../../../../.." && pwd)}"
SUN_DIR="$WORKSPACE_DIR/sun"
SOLAR_ROOT="${SOLAR_ROOT:-$(cd "$SCRIPT_DIR/../../../.." && pwd)}"
SEND_SCRIPT="$SOLAR_ROOT/core/skills/solar-telegram/scripts/send_telegram.sh"
record_notify_failure() {
  state task notice "$TASK_ID" --run "$RUN" --error "$1" --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
  echo "Task notification failed: $1 ($TASK_ID)" >&2
}
if [[ ! -x "$SEND_SCRIPT" ]]; then
  if [[ -n "$MODE" ]]; then
    echo "Task notification failed: sender_unavailable ($TASK_ID)" >&2   # an approval notice never touches the task
    exit 1
  fi
  record_notify_failure "sender_unavailable"
  exit 1
fi

# The supervisor applies SOLAR_APPROVAL_WAIT_HOURS from its own environment: the notice must announce that
# deadline, not one a workspace `.env` might set differently.
HAD_WAIT_HOURS="${SOLAR_APPROVAL_WAIT_HOURS+set}"; WAIT_HOURS="${SOLAR_APPROVAL_WAIT_HOURS:-}"
if [[ -f "$WORKSPACE_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$WORKSPACE_DIR/.env"
  set +a
fi

if [[ -n "$HAD_WAIT_HOURS" ]]; then export SOLAR_APPROVAL_WAIT_HOURS="$WAIT_HOURS"; else unset SOLAR_APPROVAL_WAIT_HOURS; fi

# The workspace `.env` carries the visible configuration (chat id, parse mode).
# The bot token is not there any more: it belongs to the process, and the
# notifier is the process. `send_telegram.sh` will not look it up on its own, so
# loading it here is what lets a completed task still reach Telegram.
# Notifications carry task titles and paths the notifier does not control. In
# Markdown a stray `_` or `*` makes Telegram reject the whole message (HTTP 400),
# so they are always sent as plain text, whatever `.env` sets.
export TELEGRAM_PARSE_MODE="none"

SECRETS_LOADER="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/solar_secrets.sh"
if [[ -f "$SECRETS_LOADER" ]]; then
  # shellcheck source=/dev/null
  source "$SECRETS_LOADER"
  solar_load_installation_secrets
fi

ORIGIN_CHAT=""
[[ -z "$MODE" ]] && ORIGIN_CHAT=$(task_field "$TASK_ID" "origin_chat_id")
CHAT_ID="${ORIGIN_CHAT:-${TELEGRAM_CHAT_ID:-}}"

PROFILE="$SUN_DIR/preferences/profile.md"
[[ ! -f "$PROFILE" ]] && PROFILE="$SUN_DIR/preferences/notifications.md"
if [[ -z "$ORIGIN_CHAT" && -f "$PROFILE" ]]; then
  # Anchor the capture on the key: a bare .* is greedy and swallows every digit
  # but the last, turning a chat id of 777 into 7.
  PROFILE_CHAT=$(grep -E "telegram_chat_id:[[:space:]]*[\"']?[0-9]+" "$PROFILE" 2>/dev/null | head -n1 | sed -E "s/.*telegram_chat_id:[[:space:]]*[\"']?([0-9]+)[\"']?.*/\1/")
  [[ -n "$PROFILE_CHAT" ]] && CHAT_ID="$PROFILE_CHAT"
fi

# An approval notice that has nowhere to go says so (3): the supervisor must not record it as sent.
NOT_SENT=0
[[ -n "$MODE" ]] && NOT_SENT=3
[[ -z "$CHAT_ID" ]] && exit "$NOT_SENT"
telegram_chat_allowed "$CHAT_ID" || exit "$NOT_SENT"

export TELEGRAM_CHAT_ID="$CHAT_ID"

LOCATION="$(task_result_location "$TASK_ID")"
TASK_STATUS=$(task_status_of "$TASK_ID")
BRIEF="Task completed: ${TITLE}"
if [[ "$TASK_STATUS" == "error" ]]; then
  BRIEF="Task failed and needs attention: ${TITLE}"
  LOCATION="" # Keep execution errors and sensitive details in local logs.
  # A task that asks for `failed` by name also gets the one-line reason (bounded, single line).
  if notify_wants failed; then
    # Only the machine code, never the provider's free text: it can carry paths, prompts or secrets.
    # The code is stored with the failure it belongs to; a failure without one says `unknown`.
    REASON="$(task_field "$TASK_ID" "failure_code" | tr -d '\r[:space:]')"
    [[ "$REASON" =~ ^[a-z][a-z0-9_]{0,39}$ ]] || REASON="unknown"
    BRIEF="${BRIEF}"$'\n'"Reason: ${REASON}"
  fi
fi
if [[ -n "$LOCATION" ]]; then
  BRIEF="${BRIEF}"$'\n'"${LOCATION}"
fi

# The delivery the executor wrote, copied into the task by the worker. It is the
# message: a fixed line plus a path to a file on the Mac cannot be read from a
# phone. `## Result` is deliberately not read here — it is the provider's full
# account, and sending it would be transport, not compression.
# (task_delivery, which reads the section, is defined above, before the lock.)
DELIVERY=""
if [[ "$TASK_STATUS" != "error" ]]; then
  DELIVERY="$(task_delivery "$TASK_ID" | sed -e '/./,$!d')"
fi

send_chunks() {
  local text="$1"
  local chunk rest
  rest="$text"
  local first=1
  while [[ -n "$rest" ]]; do
    if [[ ${#rest} -le 3500 ]]; then
      chunk="$rest"
      rest=""
    else
      chunk="${rest:0:3500}"
      rest="${rest:3500}"
    fi
    if [[ "$first" -eq 0 ]]; then
      sleep 1
    fi
    first=0
    # fd 9 is the notice lock: the sender (and anything it leaves running) must not inherit it.
    (cd "$WORKSPACE_DIR" && bash "$SEND_SCRIPT" "$chunk") 9>&- || return 1
  done
  return 0
}

if [[ -n "$MODE" ]]; then
  case "$MODE" in
    --waiting)
      # The short id and the expiry let the owner name the task and know the deadline from a phone.
      # Both come from solar-state; neither is the instructions, a path or the chat a task names.
      SHORT_ID="$(state task short-id "$TASK_ID" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["short_id"])' 2>/dev/null)"
      [[ -n "$SHORT_ID" ]] || echo "Task notification: short id unavailable ($TASK_ID)" >&2
      WAIT_LINE="$(state task wait "$TASK_ID" 2>/dev/null | python3 -c 'import json,sys
from datetime import datetime
d = json.load(sys.stdin); w = d.get("wait")
if w is None: sys.exit(0)
if not w.get("expires_at"):
    if d.get("limit_off"): print("No expiry: this wait does not end on its own.")
    sys.exit(0)
t = datetime.fromisoformat(w["expires_at"].replace("Z", "+00:00")).astimezone()
print("Expires: " + t.strftime("%Y-%m-%d %H:%M %Z") + ". If nobody authorizes it by then, the wait ends on its own.")' 2>/dev/null)"
      MESSAGE="Waiting for your approval to run: ${TITLE}"
      [[ -n "$SHORT_ID" ]] && MESSAGE="${MESSAGE}"$'\n'"Task: ${SHORT_ID}"
      MESSAGE="${MESSAGE}"$'\n'"Reason: it can change things beyond a confined read, so it needs task.authorize_run before it runs."
      # If the wait cannot be read, say so rather than leave the owner without any word on the deadline.
      [[ -z "$WAIT_LINE" ]] && WAIT_LINE="Expiry: not available right now; ask your assistant."
      MESSAGE="${MESSAGE}"$'\n'"${WAIT_LINE}"
      if [[ -n "$SHORT_ID" ]]; then
        MESSAGE="${MESSAGE}"$'\n'"Ask your assistant: review and authorize task ${SHORT_ID}."
      else
        MESSAGE="${MESSAGE}"$'\n'"Ask your assistant to review it and authorize it."
      fi ;;
    --expired-draft)
      MESSAGE="Approval wait ended: ${TITLE}"$'\n'"The task went back to draft and will not run until it is approved again." ;;
    --expired-skipped)
      MESSAGE="Approval wait ended: ${TITLE}"$'\n'"This run was skipped; the schedule is kept and the next run waits for approval again." ;;
  esac
  send_chunks "$MESSAGE" || { echo "Task notification failed: telegram_send_failed ($TASK_ID)" >&2; exit 1; }
  exit 0
fi

DELIVERY_EXPECTED=$(task_field "$TASK_ID" "delivery_expected")
if [[ -n "$DELIVERY" ]]; then
  # The delivery already ends with its own evidence line: the title and the log
  # path would only push it off the top of the screen.
  MESSAGE="$DELIVERY"
elif [[ "$DELIVERY_EXPECTED" == "true" && "$TASK_STATUS" != "error" ]]; then
  # The work ran and the log holds it, but the one-screen delivery never came.
  # Saying so beats announcing the task as resolved.
  MESSAGE="Task finished without a delivery: ${TITLE}"
  [[ -n "$LOCATION" ]] && MESSAGE="${MESSAGE}"$'\n'"${LOCATION}"
else
  MESSAGE="$BRIEF"
fi

# Last look before sending: the task must still be in the status and run this message was built from.
# A failure requeued without a new claim keeps its run but is no longer an error: it gets no notice.
if [[ -z "$MODE" ]]; then
  NOW="$(state task snapshot "$TASK_ID" 2>/dev/null | python3 -c 'import json,sys
d=json.load(sys.stdin); print(d["status"] + " " + (d["fields"].get("notify_run") or ""))' 2>/dev/null)"
  if [[ -z "$NOW" ]]; then
    # The last read failed: say the notice was lost, as the first read does.
    state task notice "$TASK_ID" --run "$RUN" --error notify_snapshot_failed --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1
    echo "Task notification failed: notify_snapshot_failed ($TASK_ID)" >&2
    exit 1
  fi
  [[ "$NOW" == "$SNAPSHOT_STATUS $RUN" ]] || exit 0
fi
send_chunks "$MESSAGE" || { record_notify_failure "telegram_send_failed"; exit 1; }

state task notice "$TASK_ID" --run "$RUN" >/dev/null   # one transaction, only while this run is still the current one
