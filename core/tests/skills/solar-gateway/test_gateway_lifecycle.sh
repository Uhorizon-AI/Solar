#!/usr/bin/env bash
# Unit tests for solar-gateway lifecycle (lock, stamp, stop ownership helpers).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LIB="$CORE_ROOT/skills/solar-gateway/scripts/transport_gateway_lib.sh"
STOP="$CORE_ROOT/skills/solar-gateway/scripts/stop_transport_gateway.sh"
SETUP="$CORE_ROOT/skills/solar-gateway/scripts/setup_transport_gateway.sh"
ENSURE="$CORE_ROOT/skills/solar-gateway/scripts/ensure_transport_gateway.sh"
LIST_SUPPORTED="$CORE_ROOT/skills/solar-router/scripts/list_supported_providers.sh"

PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  local out code=0
  out="$("$@" 2>&1)" || code=$?
  if [[ "$code" -eq 0 ]]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    echo "$out" | sed 's/^/  /' >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_fail() {
  local label="$1"
  shift
  local out code=0
  out="$("$@" 2>&1)" || code=$?
  if [[ "$code" -ne 0 ]]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label (expected failure)" >&2
    echo "$out" | sed 's/^/  /' >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -q "$needle"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label (missing: $needle)" >&2
    echo "$haystack" | sed 's/^/  /' >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_eq() {
  local label="$1" got="$2" want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label (got='$got' want='$want')" >&2
    FAIL=$((FAIL + 1))
  fi
}

# Call lib functions in-process (not via assert_ok subshell).
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

write_env() {
  cat >"$WS/.env" <<EOF
SOLAR_ROUTER_PROVIDER_PRIORITY=${1:-codex,claude}
SOLAR_WS_PORT=${SOLAR_WS_PORT:-18765}
SOLAR_HTTP_PORT=${SOLAR_HTTP_PORT:-18787}
SOLAR_HTTP_HOST=127.0.0.1
SOLAR_GATEWAY_RUN_DIR=${SOLAR_GATEWAY_RUN_DIR:-$TMP/run}
SOLAR_TUNNEL_MODE=quick
EOF
}

rebind() {
  _TGW_BOUND=
  transport_gateway_bind_workspace
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; kill $(jobs -p) 2>/dev/null || true' EXIT

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/.solar"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' >"$WS/.solar/manifest.json"
SOLAR_WS_PORT=18765
SOLAR_HTTP_PORT=18787
SOLAR_GATEWAY_RUN_DIR="$TMP/run"
write_env "codex,claude"
mkdir -p "$TMP/run"

export SOLAR_WORKSPACE="$WS"
export SOLAR_ROOT="$(cd "$CORE_ROOT/.." && pwd)"
export GATEWAY_BACKOFF_BASE_SEC=1
export GATEWAY_BACKOFF_CAP_SEC=4

# shellcheck source=/dev/null
source "$LIB"
rebind

# --- list_supported_providers ---
SUPPORTED_OUT="$(bash "$LIST_SUPPORTED")"
assert_contains "supported providers include codex" "$SUPPORTED_OUT" "codex"
assert_contains "supported providers include agy" "$SUPPORTED_OUT" "agy"
assert_fail "gemini not in supported providers" bash -c "bash '$LIST_SUPPORTED' | grep -qx gemini"

# --- fingerprint / stamp ---
FP1="$(gateway_compute_fingerprint)"
if [[ -n "$FP1" ]]; then pass "fingerprint non-empty"; else fail "fingerprint non-empty"; fi
gateway_write_stamp
if [[ -f "$(gateway_stamp_path)" ]]; then pass "stamp file exists"; else fail "stamp file exists"; fi
assert_eq "stamp fingerprint matches" "$(gateway_stamp_get fingerprint)" "$FP1"
if gateway_has_drift; then fail "no drift when stamp matches"; else pass "no drift when stamp matches"; fi

write_env "codex,claude,agy"
rebind
FP2="$(gateway_compute_fingerprint)"
if [[ "$FP1" != "$FP2" ]]; then pass "fingerprint changes on priority"; else fail "fingerprint changes on priority"; fi
if gateway_has_drift; then pass "drift when fingerprint differs"; else fail "drift when fingerprint differs"; fi

write_env "codex,claude"
rebind
gateway_write_stamp

# --- previous runtime metadata ---
SOLAR_GATEWAY_RUN_DIR="$TMP/run2"
SOLAR_WS_PORT=28765
SOLAR_HTTP_PORT=28787
export SOLAR_GATEWAY_RUN_DIR SOLAR_WS_PORT SOLAR_HTTP_PORT
write_env "codex,claude"
rebind
gateway_write_stamp
assert_eq "previous_run_dir preserved" "$(gateway_stamp_get previous_run_dir)" "$TMP/run"
assert_eq "previous_ws_port preserved" "$(gateway_stamp_get previous_ws_port)" "18765"

SOLAR_GATEWAY_RUN_DIR="$TMP/run"
SOLAR_WS_PORT=18765
SOLAR_HTTP_PORT=18787
export SOLAR_GATEWAY_RUN_DIR SOLAR_WS_PORT SOLAR_HTTP_PORT
write_env "codex,claude"
rebind
gateway_write_stamp

# --- mkdir-lock ---
rm -rf "$(gateway_lock_dir)"
# Hold lock from a process whose cmdline looks like a real gateway op.
HOLDER_SCRIPT="$TMP/ensure_transport_gateway.sh"
cat >"$HOLDER_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT'
source '$LIB'
transport_gateway_bind_workspace
gateway_acquire_lock
gateway_install_lock_trap
# Keep lock held until killed by the test.
while true; do sleep 1; done
EOF
chmod +x "$HOLDER_SCRIPT"
bash "$HOLDER_SCRIPT" &
HOLDER_LOCK_PID=$!
sleep 0.3
if [[ -f "$(gateway_lock_dir)/pid" ]]; then pass "acquire lock"; else fail "acquire lock"; fi
assert_eq "lock owned by holder" "$(cat "$(gateway_lock_dir)/pid")" "$HOLDER_LOCK_PID"
# second acquire should fail while holder is a real gateway-named process
assert_fail "second acquire blocked" bash -c "
  export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT'
  source '$LIB'
  transport_gateway_bind_workspace
  gateway_acquire_lock
"
kill -9 "$HOLDER_LOCK_PID" 2>/dev/null || true
wait "$HOLDER_LOCK_PID" 2>/dev/null || true
rm -rf "$(gateway_lock_dir)"
if [[ ! -d "$(gateway_lock_dir)" ]]; then pass "lock dir gone after release"; else fail "lock dir gone after release"; fi

# dead pid recovery
mkdir -p "$(gateway_lock_dir)"
echo "999999" >"$(gateway_lock_dir)/pid"
if gateway_acquire_lock; then pass "dead pid lock reclaimed"; else fail "dead pid lock reclaimed"; fi
gateway_release_lock

# recycled pid (alive, foreign cmdline) — override cmdline helper so the test
# does not depend on sandbox ps permissions.
sleep 30 &
FOREIGN_PID=$!
mkdir -p "$(gateway_lock_dir)"
echo "$FOREIGN_PID" >"$(gateway_lock_dir)/pid"
gateway_pid_cmdline() {
  local pid="$1"
  if [[ "$pid" == "$FOREIGN_PID" ]]; then
    echo "/usr/bin/sleep 30"
    return 0
  fi
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  ps -p "$pid" -o args= 2>/dev/null || true
}
if gateway_acquire_lock; then pass "recycled pid lock reclaimed"; else fail "recycled pid lock reclaimed"; fi
gateway_release_lock
unset -f gateway_pid_cmdline
# Re-declare original from a fresh subshell eval of the function body is hard;
# re-source lib functions (keep workspace bound).
_TGW_BOUND=1
# shellcheck source=/dev/null
source "$LIB"
_TGW_BOUND=1
kill -9 "$FOREIGN_PID" 2>/dev/null || true
wait "$FOREIGN_PID" 2>/dev/null || true

# SOLAR_GATEWAY_LOCK_HELD re-entry (must match parent lock pid).
# Run child without command-substitution so PPID == this shell (lock owner).
gateway_acquire_lock
set +e
bash -c "
  export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT' SOLAR_GATEWAY_LOCK_HELD=1
  source '$LIB'
  transport_gateway_bind_workspace
  gateway_acquire_lock
  [[ \${_GATEWAY_LOCK_OWNED} == 0 ]]
"
_lock_held_code=$?
set -e
if [[ "$_lock_held_code" -eq 0 ]]; then
  pass "child with LOCK_HELD + parent lock"
else
  fail "child with LOCK_HELD + parent lock"
fi
gateway_release_lock

# Spoof LOCK_HELD without owning lock → falls through and acquires normally
assert_ok "spoof LOCK_HELD without lock acquires normally" bash -c "
  export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT' SOLAR_GATEWAY_LOCK_HELD=1
  source '$LIB'
  transport_gateway_bind_workspace
  rm -rf \"\$(gateway_lock_dir)\"
  gateway_acquire_lock
  [[ \${_GATEWAY_LOCK_OWNED} == 1 ]]
  gateway_release_lock
"

assert_ok "manual acquire without LOCK_HELD" bash -c "
  export SOLAR_WORKSPACE='$WS' SOLAR_ROOT='$SOLAR_ROOT'
  unset SOLAR_GATEWAY_LOCK_HELD
  source '$LIB'
  transport_gateway_bind_workspace
  gateway_acquire_lock && gateway_release_lock
"

# no flock command usage (comments mentioning flock are ok)
if grep -nE '(^|[[:space:]])flock([[:space:]]|$)|flock\(' "$LIB" "$STOP" "$SETUP" "$ENSURE" 2>/dev/null | grep -vE '^\s*#|no flock|not flock|portable' >/dev/null; then
  fail "sources must not invoke flock"
else
  pass "sources must not invoke flock"
fi

# --- env.fail backoff ---
gateway_write_env_fail "test_fail"
if [[ -f "$(gateway_fail_path)" ]]; then pass "env.fail exists"; else fail "env.fail exists"; fi
if gateway_backoff_active; then pass "backoff active immediately"; else fail "backoff active immediately"; fi
write_env "claude"
rebind
if gateway_backoff_active; then fail "backoff resets on fingerprint change"; else pass "backoff resets on fingerprint change"; fi
write_env "codex,claude"
rebind
gateway_write_stamp
rm -f "$(gateway_fail_path)"

# --- stale pid unlink (dead pid, free port) ---
echo "999998" >"$TMP/run/ws.pid"
DRY="$(bash "$STOP" --dry-run 2>&1 || true)"
assert_contains "dry-run reports unlink_stale_pid" "$DRY" "unlink_stale_pid"
bash "$STOP" >/dev/null 2>&1 || true
if [[ ! -f "$TMP/run/ws.pid" ]]; then pass "stale ws.pid removed"; else fail "stale ws.pid removed"; fi

# --- stop dry-run: foreign (non-cloudflared) pid in cloudflared.pid ---
sleep 60 &
FAKE=$!
echo "$FAKE" >"$TMP/run/cloudflared.pid"
DRY2="$(bash "$STOP" --dry-run --tunnel-only 2>&1 || true)"
if printf '%s' "$DRY2" | grep -qE 'action=(skip|unlink_stale_pid)'; then
  pass "foreign tunnel reported skip or unlink"
else
  fail "foreign tunnel reported skip or unlink"
  echo "$DRY2" | sed 's/^/  /' >&2
fi
kill "$FAKE" 2>/dev/null || true
wait "$FAKE" 2>/dev/null || true
rm -f "$TMP/run/cloudflared.pid"

# --- setup --prepare-only ---
assert_ok "setup --prepare-only" bash "$SETUP" --prepare-only

# --- setup refuses busy port without --restart ---
python3 - <<PY &
import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 18765))
s.listen(1)
time.sleep(30)
PY
HOLDER=$!
sleep 0.3
set +e
BUSY_OUT="$(bash "$SETUP" 2>&1)"
BUSY_CODE=$?
set -e
kill "$HOLDER" 2>/dev/null || true
wait "$HOLDER" 2>/dev/null || true
if [[ "$BUSY_CODE" -ne 0 ]]; then pass "setup fails on busy port without --restart"; else fail "setup fails on busy port without --restart"; fi
assert_contains "setup busy message" "$BUSY_OUT" "Refusing to reuse"

# --- preflight rejects unsupported provider ---
write_env "gemini,codex"
rebind
set +e
PRE_OUT="$(gateway_preflight 2>&1)"
PRE_CODE=$?
set -e
if [[ "$PRE_CODE" -ne 0 ]]; then pass "preflight fails on gemini"; else fail "preflight fails on gemini"; fi
assert_contains "preflight mentions unsupported" "$PRE_OUT" "unsupported provider"
write_env "codex,claude"
rebind

# --- stamp absent + no bridges → no drift ---
rm -f "$(gateway_stamp_path)"
if gateway_has_drift; then fail "no drift when stamp absent and no bridges"; else pass "no drift when stamp absent and no bridges"; fi

# --- fail attempt cap (hard stop, not infinite spaced retries) ---
export GATEWAY_FAIL_ATTEMPTS_CAP=3
GATEWAY_FAIL_ATTEMPTS_CAP=3
rm -f "$(gateway_fail_path)"
gateway_write_env_fail "t1"
gateway_write_env_fail "t2"
gateway_write_env_fail "t3"
if gateway_fail_exhausted; then pass "fail cap exhausted after N attempts"; else fail "fail cap exhausted after N attempts"; fi
if gateway_backoff_active; then pass "backoff active when exhausted"; else fail "backoff active when exhausted"; fi
# Even if next_retry_at were in the past, exhausted must block
sed -i.bak 's/^next_retry_at=.*/next_retry_at=0/' "$(gateway_fail_path)" 2>/dev/null \
  || sed -i '' 's/^next_retry_at=.*/next_retry_at=0/' "$(gateway_fail_path)"
if gateway_backoff_active; then pass "exhausted blocks even when next_retry_at past"; else fail "exhausted blocks even when next_retry_at past"; fi
write_env "agy"
rebind
if gateway_fail_exhausted; then fail "exhausted resets on fingerprint change"; else pass "exhausted resets on fingerprint change"; fi
write_env "codex,claude"
rebind
rm -f "$(gateway_fail_path)"
export GATEWAY_FAIL_ATTEMPTS_CAP=5
GATEWAY_FAIL_ATTEMPTS_CAP=5

# --- tunnel ownership uses previous stamp metadata ---
export SOLAR_TUNNEL_MODE=named
export SOLAR_CLOUDFLARED_TUNNEL_NAME=old-tunnel
export SOLAR_CLOUDFLARED_CONFIG="$TMP/old-tunnel.yml"
export SOLAR_HTTP_HOST=127.0.0.1
touch "$TMP/old-tunnel.yml"
write_env "codex,claude"
# keep tunnel vars in env file for bind
{
  echo "SOLAR_TUNNEL_MODE=named"
  echo "SOLAR_CLOUDFLARED_TUNNEL_NAME=old-tunnel"
  echo "SOLAR_CLOUDFLARED_CONFIG=$TMP/old-tunnel.yml"
} >>"$WS/.env"
rebind
gateway_write_stamp
# Change to new tunnel identity (would falsely mark old process foreign without previous_*)
export SOLAR_CLOUDFLARED_TUNNEL_NAME=new-tunnel
export SOLAR_CLOUDFLARED_CONFIG="$TMP/new-tunnel.yml"
touch "$TMP/new-tunnel.yml"
gateway_pid_cmdline() {
  echo "cloudflared tunnel --config $TMP/old-tunnel.yml run old-tunnel"
}
# Fake pid file + kill -0: use a live sleep pid
sleep 30 &
TUN_PID=$!
echo "$TUN_PID" >"$TMP/run/cloudflared.pid"
if gateway_tunnel_owned "$TUN_PID" "$TMP/run"; then
  pass "tunnel owned via previous stamp metadata"
else
  fail "tunnel owned via previous stamp metadata"
fi
unset -f gateway_pid_cmdline
_TGW_BOUND=1
# shellcheck source=/dev/null
source "$LIB"
_TGW_BOUND=1
kill -9 "$TUN_PID" 2>/dev/null || true
wait "$TUN_PID" 2>/dev/null || true
rm -f "$TMP/run/cloudflared.pid"
# restore quick mode
export SOLAR_TUNNEL_MODE=quick
unset SOLAR_CLOUDFLARED_TUNNEL_NAME SOLAR_CLOUDFLARED_CONFIG
write_env "codex,claude"
rebind

# --- telegram failure: functional rollback harness (processes + pid files cleaned) ---
FAKE_BIN="$TMP/fakebin"
mkdir -p "$FAKE_BIN"
cat >"$FAKE_BIN/cloudflared" <<'EOF'
#!/usr/bin/env bash
# Fake tunnel: emit a quick-tunnel URL then stay alive until killed.
echo "INF https://tg-rollback-test.trycloudflare.com"
while true; do sleep 1; done
EOF
chmod +x "$FAKE_BIN/cloudflared"
cat >"$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *api.telegram.org* ]]; then
  echo '{"ok":true,"result":{"url":""}}'
else
  exec /usr/bin/curl "$@"
fi
EOF
chmod +x "$FAKE_BIN/curl"

# Ensure free ports and clean run dir for this harness
for p in 18765 18787; do
  old="$(lsof -nP -iTCP:"$p" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
  if [[ -n "$old" ]]; then kill -9 "$old" 2>/dev/null || true; fi
done
rm -rf "$TMP/run"
mkdir -p "$TMP/run"
write_env "codex,claude"
# Token present so setup enters the telegram block; true is required for FORCE fail
echo "TELEGRAM_BOT_TOKEN=test-token-not-real" >>"$WS/.env"
echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=true" >>"$WS/.env"
rebind

# setup prepends its system PATH, so use exported functions for isolation.
export FAKE_BIN
curl() {
  if [[ "$*" == *api.telegram.org* ]]; then
    echo '{"ok":true,"result":{"url":""}}'
  else
    command curl "$@"
  fi
}
nohup() {
  if [[ "${1:-}" == cloudflared ]]; then
    shift
    command nohup "$FAKE_BIN/cloudflared" "$@"
  else
    command nohup "$@"
  fi
}
export -f curl nohup
set +e
TG_OUT="$(
  PATH="$FAKE_BIN:$PATH" \
  SOLAR_WORKSPACE="$WS" \
  SOLAR_ROOT="$SOLAR_ROOT" \
  SOLAR_GATEWAY_FORCE_TELEGRAM_FAIL=1 \
  bash "$SETUP" 2>&1
)"
TG_CODE=$?
set -e
unset -f curl nohup

if [[ "$TG_CODE" -ne 0 ]]; then
  pass "telegram force-fail exits non-zero"
else
  fail "telegram force-fail exits non-zero"
  echo "$TG_OUT" | sed 's/^/  /' >&2
fi
if printf '%s' "$TG_OUT" | grep -q 'rolling back'; then
  pass "telegram force-fail logs rollback"
else
  fail "telegram force-fail logs rollback"
  echo "$TG_OUT" | sed 's/^/  /' >&2
fi

# Bridges / tunnel must not remain after rollback
alive=0
for pf in "$TMP/run/ws.pid" "$TMP/run/http.pid" "$TMP/run/cloudflared.pid"; do
  if [[ -f "$pf" ]]; then
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      alive=1
      echo "  still alive: $pf -> $pid" >&2
    fi
  fi
done
ws_listen="$(lsof -nP -iTCP:18765 -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
http_listen="$(lsof -nP -iTCP:18787 -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
if [[ "$alive" -eq 0 && -z "$ws_listen" && -z "$http_listen" ]]; then
  pass "telegram rollback leaves no live gateway processes"
else
  fail "telegram rollback leaves no live gateway processes"
fi
if [[ ! -f "$(gateway_stamp_path)" ]] || ! grep -q . "$(gateway_stamp_path)" 2>/dev/null; then
  # stamp should not be a success stamp from this failed run; absent or stale ok if fingerprint not matching new success
  :
fi
if [[ ! -f "$(gateway_stamp_path)" ]]; then
  pass "telegram rollback writes no success stamp"
else
  # If a prior stamp from earlier tests exists, ensure this failed run did not refresh it to current fp
  fp_now="$(gateway_compute_fingerprint)"
  stamped="$(gateway_stamp_get fingerprint || true)"
  if [[ "$stamped" != "$fp_now" ]]; then
    pass "telegram rollback writes no success stamp"
  else
    fail "telegram rollback writes no success stamp"
  fi
fi

# --- Telegram claim / n8n secret fingerprint ---
unset SOLAR_TELEGRAM_WEBHOOK_OWNER || true
unset SOLAR_TELEGRAM_WEBHOOK || true
unset SOLAR_GATEWAY_CLAIM_TELEGRAM || true
unset SOLAR_N8N_WEBHOOK_SECRET || true
unset TELEGRAM_BOT_TOKEN || true
write_env "codex,claude"
rebind
assert_eq "default claim flag is absent" "$(gateway_telegram_claim)" ""
assert_eq "default claim label is absent" "$(gateway_telegram_claim_label)" "absent"
assert_eq "http channels without token" "$(gateway_http_channels_label)" "n8n"

echo "SOLAR_TELEGRAM_WEBHOOK_OWNER=external" >>"$WS/.env"
rebind
assert_eq "OWNER is ignored" "$(gateway_telegram_claim)" ""

grep -v '^SOLAR_TELEGRAM_WEBHOOK_OWNER=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
echo "SOLAR_TELEGRAM_WEBHOOK=true" >>"$WS/.env"
rebind
assert_eq "legacy SOLAR_TELEGRAM_WEBHOOK is ignored" "$(gateway_telegram_claim)" ""

grep -v '^SOLAR_TELEGRAM_WEBHOOK=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
write_env "codex,claude"
rebind
FP_WH_BASE="$(gateway_compute_fingerprint)"
echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=false" >>"$WS/.env"
rebind
FP_WH_FALSE="$(gateway_compute_fingerprint)"
if [[ "$FP_WH_BASE" != "$FP_WH_FALSE" ]]; then
  pass "fingerprint changes when SOLAR_GATEWAY_CLAIM_TELEGRAM=false"
else
  fail "fingerprint changes when SOLAR_GATEWAY_CLAIM_TELEGRAM=false"
fi

grep -v '^SOLAR_GATEWAY_CLAIM_TELEGRAM=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=bogus" >>"$WS/.env"
rebind
if ! gateway_preflight >/dev/null 2>&1; then
  pass "preflight fails on invalid SOLAR_GATEWAY_CLAIM_TELEGRAM"
else
  fail "preflight fails on invalid SOLAR_GATEWAY_CLAIM_TELEGRAM"
fi

grep -v '^SOLAR_GATEWAY_CLAIM_TELEGRAM=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
write_env "codex,claude"
rebind

FP_SEC_A_ENV="secret-value-aaaa-bbbb-cccc-dddd-eeee-ffff"
FP_SEC_B_ENV="secret-value-1111-2222-3333-4444-5555-6666"
grep -v '^SOLAR_N8N_WEBHOOK_SECRET=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
echo "SOLAR_N8N_WEBHOOK_SECRET=${FP_SEC_A_ENV}" >>"$WS/.env"
rebind
FP_SEC_A="$(gateway_compute_fingerprint)"
SEC_HASH_A="$(gateway_n8n_webhook_secret_sha256)"
grep -v '^SOLAR_N8N_WEBHOOK_SECRET=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
echo "SOLAR_N8N_WEBHOOK_SECRET=${FP_SEC_B_ENV}" >>"$WS/.env"
rebind
FP_SEC_B="$(gateway_compute_fingerprint)"
SEC_HASH_B="$(gateway_n8n_webhook_secret_sha256)"
if [[ -n "$SEC_HASH_A" && -n "$SEC_HASH_B" && "$SEC_HASH_A" != "$SEC_HASH_B" && "$FP_SEC_A" != "$FP_SEC_B" ]]; then
  pass "fingerprint changes when n8n secret rotates"
else
  fail "fingerprint changes when n8n secret rotates"
fi
MATERIAL="$(gateway_collect_fingerprint_material)"
if printf '%s' "$MATERIAL" | grep -Fq "$FP_SEC_B_ENV"; then
  fail "fingerprint material excludes plaintext n8n secret"
else
  pass "fingerprint material excludes plaintext n8n secret"
fi
assert_contains "fingerprint material includes secret sha key" "$MATERIAL" "SOLAR_N8N_WEBHOOK_SECRET_SHA256="

SET_TG="$CORE_ROOT/skills/solar-gateway/scripts/set_telegram_webhook.sh"
grep -v '^SOLAR_GATEWAY_CLAIM_TELEGRAM=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=false" >>"$WS/.env"
rebind
SET_OUT="$(bash "$SET_TG" 2>&1)" && SET_CODE=0 || SET_CODE=$?
if [[ "$SET_CODE" -eq 0 ]] && printf '%s' "$SET_OUT" | grep -qi "omitting setWebhook"; then
  pass "set_telegram_webhook omits setWebhook when false"
else
  fail "set_telegram_webhook omits setWebhook when false"
  echo "$SET_OUT" | sed 's/^/  /' >&2
fi

VERIFY_TG="$CORE_ROOT/skills/solar-gateway/scripts/verify_telegram_webhook.sh"
STUB_BIN="$TMP/bin"
mkdir -p "$STUB_BIN"
cat >"$STUB_BIN/curl" <<'STUB'
#!/usr/bin/env bash
echo '{"ok":true,"result":{"url":"https://wrong.example/webhook/telegram","has_custom_certificate":false,"pending_update_count":0}}'
STUB
chmod +x "$STUB_BIN/curl"
grep -v '^SOLAR_GATEWAY_CLAIM_TELEGRAM=' "$WS/.env" >"$WS/.env.bak" || true
mv "$WS/.env.bak" "$WS/.env"
echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=true" >>"$WS/.env"
echo "TELEGRAM_BOT_TOKEN=test-token" >>"$WS/.env"
echo "SOLAR_CLOUDFLARED_HOSTNAME=solar-ai.uhorizon.ai" >>"$WS/.env"
echo "SOLAR_HTTP_WEBHOOK_BASE=/webhook" >>"$WS/.env"
rebind
SET_OUT="$(PATH="$STUB_BIN:$PATH" bash "$SET_TG" 2>&1)" && SET_CODE=0 || SET_CODE=$?
if [[ "$SET_CODE" -ne 0 ]] && printf '%s' "$SET_OUT" | grep -qi "refusing setWebhook"; then
  pass "set_telegram_webhook true + foreign URL exits 1"
else
  fail "set_telegram_webhook true + foreign URL exits 1"
  echo "$SET_OUT" | sed 's/^/  /' >&2
fi

SETUP_LIB_OUT="$(
  PATH="$STUB_BIN:$PATH" \
  SOLAR_GATEWAY_CLAIM_TELEGRAM=true \
  TELEGRAM_BOT_TOKEN=test-token \
  SOLAR_CLOUDFLARED_HOSTNAME=solar-ai.uhorizon.ai \
  SOLAR_HTTP_WEBHOOK_BASE=/webhook \
  bash -c 'source "'"$LIB"'" && gateway_telegram_lifecycle_setup'
)" && SETUP_LIB_CODE=0 || SETUP_LIB_CODE=$?
if [[ "$SETUP_LIB_CODE" -eq 0 ]] && printf '%s' "$SETUP_LIB_OUT" | grep -qi "not claiming"; then
  pass "setup lifecycle skips foreign URL without rollback"
else
  fail "setup lifecycle skips foreign URL without rollback"
  echo "$SETUP_LIB_OUT" | sed 's/^/  /' >&2
fi

VERIFY_OUT="$(PATH="$STUB_BIN:$PATH" bash "$VERIFY_TG" 2>&1)" && VERIFY_CODE=0 || VERIFY_CODE=$?
if [[ "$VERIFY_CODE" -ne 0 ]] && printf '%s' "$VERIFY_OUT" | grep -qi "mismatch"; then
  pass "verify_telegram_webhook fails on URL mismatch"
else
  fail "verify_telegram_webhook fails on URL mismatch"
  echo "$VERIFY_OUT" | sed 's/^/  /' >&2
fi

# A failed or malformed ownership lookup must never authorize setWebhook.
for lookup_mode in network invalid api_error; do
  cat >"$STUB_BIN/curl" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *getWebhookInfo* ]]; then
  case "$LOOKUP_MODE" in
    network) exit 7 ;;
    invalid) echo 'not-json' ;;
    api_error) echo '{"ok":false,"description":"failure"}' ;;
  esac
else
  echo called >>"$SET_CALLED"
  echo '{"ok":true}'
fi
STUB
  export LOOKUP_MODE="$lookup_mode" SET_CALLED="$TMP/set-called"
  rm -f "$SET_CALLED"
  assert_fail "setWebhook refuses $lookup_mode lookup" env PATH="$STUB_BIN:$PATH" bash "$SET_TG"
  assert_ok "lifecycle survives $lookup_mode lookup" env PATH="$STUB_BIN:$PATH" \
    SOLAR_GATEWAY_CLAIM_TELEGRAM=true TELEGRAM_BOT_TOKEN=test-token \
    SOLAR_CLOUDFLARED_HOSTNAME=solar.example \
    bash -c 'source "$1"; gateway_telegram_lifecycle_setup' bash "$LIB"
  if [[ ! -f "$SET_CALLED" ]]; then pass "no setWebhook after $lookup_mode lookup"; else fail "unsafe claim"; fi
done

write_env "codex,claude"
rebind
rm -f "$(gateway_fail_path)"

# --- priority smoke restoration must be strict ---
SMOKE="$SCRIPT_DIR/smoke_priority_ensure.sh"
if grep -n 'bash "\$ENSURE".*|| true' "$SMOKE" >/dev/null 2>&1; then
  fail "priority smoke must not ignore restore ensure failure"
else
  pass "priority smoke does not ignore restore ensure failure"
fi
if grep -q 'gateway is not healthy after smoke restoration' "$SMOKE" \
  && grep -q 'restored env fingerprint does not match env.stamp' "$SMOKE" \
  && grep -q 'restored gateway processes do not contain priority' "$SMOKE"; then
  pass "priority smoke verifies restored health, stamp, and process env"
else
  fail "priority smoke verifies restored health, stamp, and process env"
fi

# cleanup token line for remaining tests
write_env "codex,claude"
rebind
rm -f "$(gateway_fail_path)"

echo ""
echo "Results: PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
