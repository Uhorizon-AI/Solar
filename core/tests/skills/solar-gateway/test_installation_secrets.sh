#!/usr/bin/env bash
# The gateway takes its sending credentials from the process, not the workspace.
#
# `TELEGRAM_BOT_TOKEN` and `SOLAR_N8N_WEBHOOK_SECRET` left `Solar/.env` because
# that file sits in the tree the IDE indexes. They now live in a 0600 store
# outside it, and `transport_gateway_bind_workspace` is what puts them in the
# environment the bridge inherits.
#
# Fixtures only: a temp workspace and a temp store. The machine's real store is
# never read and never written.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LIB="$CORE_ROOT/skills/solar-gateway/scripts/transport_gateway_lib.sh"

PASS=0
FAIL=0

assert_eq() {
  local label="$1" got="$2" want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: $label"; PASS=$((PASS + 1))
  else
    echo "FAIL: $label (got='$got' want='$want')" >&2; FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/.solar"
echo '{"layout":"solar-client-v1.2","core_source":"global"}' >"$WS/.solar/settings.json"

# The workspace keeps the visible configuration only.
cat >"$WS/.env" <<'EOF'
# [solar-telegram] required environment
TELEGRAM_CHAT_ID=4242
TELEGRAM_PARSE_MODE=Markdown
# [solar-gateway] required environment
SOLAR_WS_PORT=18765
SOLAR_HTTP_PORT=18787
EOF

STORE="$TMP/app-data/Solar/secrets/installation.env"
mkdir -p "$(dirname "$STORE")"
cat >"$STORE" <<'EOF'
TELEGRAM_BOT_TOKEN=token-from-the-process
SOLAR_N8N_WEBHOOK_SECRET=secret-from-the-process
EOF
chmod 600 "$STORE"

SOLAR_ROOT="$(cd "$CORE_ROOT/.." && pwd)"

bound() {
  # One bind per subshell: the lib memoises it.
  local expr="$1"
  local extra_env="${2:-}"
  bash -c "
    set -euo pipefail
    export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT' SOLAR_SECRETS_FILE='$STORE'
    $extra_env
    source '$LIB'
    transport_gateway_bind_workspace
    printf '%s' \"$expr\"
  "
}

assert_eq "the bot token comes from the store" \
  "$(bound '${TELEGRAM_BOT_TOKEN:-}')" "token-from-the-process"
assert_eq "the n8n secret comes from the store" \
  "$(bound '${SOLAR_N8N_WEBHOOK_SECRET:-}')" "secret-from-the-process"
assert_eq "the workspace still supplies the visible configuration" \
  "$(bound '${TELEGRAM_CHAT_ID:-}')" "4242"

# A leftover copy in the workspace must not win: the store is the authority for
# these two names, so a stale `.env` cannot quietly send with an old token.
cat >>"$WS/.env" <<'EOF'
TELEGRAM_BOT_TOKEN=stale-in-the-workspace
SOLAR_N8N_WEBHOOK_SECRET=stale-in-the-workspace
EOF
assert_eq "a stale token in .env loses to the store" \
  "$(bound '${TELEGRAM_BOT_TOKEN:-}')" "token-from-the-process"
assert_eq "a stale n8n secret in .env loses to the store" \
  "$(bound '${SOLAR_N8N_WEBHOOK_SECRET:-}')" "secret-from-the-process"

# A machine with no store configured still binds: the callers fail closed on the
# missing key with their own message, the bind does not explode.
EMPTY="$TMP/absent.env"
assert_eq "binding survives a machine with no store" \
  "$(bash -c "
    set -euo pipefail
    export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT' SOLAR_SECRETS_FILE='$EMPTY'
    source '$LIB'
    transport_gateway_bind_workspace
    printf 'bound'
  ")" "bound"

echo ""
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
