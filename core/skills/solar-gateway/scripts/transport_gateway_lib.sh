#!/usr/bin/env bash
# transport_gateway_lib.sh — workspace bind + gateway lifecycle helpers.
# Sourced by stop/setup/ensure/check scripts. Do not execute directly.
set -euo pipefail

_TGW_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_RESOLVE_SCRIPT="$_TGW_LIB_DIR/../../solar-client/scripts/resolve_solar_paths.sh"

# Backoff: 30s, 60s, 120s, ... capped at 15 minutes.
# After GATEWAY_FAIL_ATTEMPTS_CAP failures with the same fingerprint, stop retrying
# until the fingerprint changes (hard stop — not just spaced forever).
GATEWAY_BACKOFF_BASE_SEC="${GATEWAY_BACKOFF_BASE_SEC:-30}"
GATEWAY_BACKOFF_CAP_SEC="${GATEWAY_BACKOFF_CAP_SEC:-900}"
GATEWAY_FAIL_ATTEMPTS_CAP="${GATEWAY_FAIL_ATTEMPTS_CAP:-5}"

transport_gateway_bind_workspace() {
  if [[ -n "${_TGW_BOUND:-}" ]]; then
    return 0
  fi
  # shellcheck source=/dev/null
  source "$_RESOLVE_SCRIPT"
  if [[ -n "${SOLAR_WORKSPACE:-}" ]]; then
    solar_resolve_paths --workspace "$SOLAR_WORKSPACE" --quiet
  else
    solar_resolve_paths --quiet
  fi
  cd "$SOLAR_WORKSPACE"
  if [[ -f "$SOLAR_WORKSPACE/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SOLAR_WORKSPACE/.env"
    set +a
  fi
  _TGW_BOUND=1
}

transport_gateway_script() {
  local name="$1"
  transport_gateway_bind_workspace
  printf '%s/skills/solar-gateway/scripts/%s' "$(solar_core_dir)" "$name"
}

transport_gateway_router_script() {
  local name="$1"
  transport_gateway_bind_workspace
  printf '%s/skills/solar-router/scripts/%s' "$(solar_core_dir)" "$name"
}

# ---------------------------------------------------------------------------
# Stable runtime paths (workspace-scoped, not /tmp)
# ---------------------------------------------------------------------------

gateway_runtime_dir() {
  transport_gateway_bind_workspace
  printf '%s/sun/runtime/gateway' "$SOLAR_WORKSPACE"
}

gateway_stamp_path() {
  printf '%s/env.stamp' "$(gateway_runtime_dir)"
}

gateway_fail_path() {
  printf '%s/env.fail' "$(gateway_runtime_dir)"
}

gateway_lock_dir() {
  printf '%s/lock' "$(gateway_runtime_dir)"
}

gateway_ensure_runtime_dir() {
  mkdir -p "$(gateway_runtime_dir)"
}

gateway_run_dir() {
  printf '%s' "${SOLAR_GATEWAY_RUN_DIR:-/tmp/solar-transport-gateway}"
}

gateway_ws_port() {
  printf '%s' "${SOLAR_WS_PORT:-8765}"
}

gateway_http_port() {
  printf '%s' "${SOLAR_HTTP_PORT:-8787}"
}

# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

gateway_pid_cmdline() {
  local pid="$1"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  # macOS: args= ; Linux: args= also works with ps from procps.
  ps -p "$pid" -o args= 2>/dev/null || ps -p "$pid" -o command= 2>/dev/null || true
}

gateway_listener_pid_for_port() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 1
  fi
  local pid
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  echo "$pid"
}

gateway_port_is_free() {
  local port="$1"
  local pid=""
  pid="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
  [[ -z "$pid" ]]
}

gateway_is_bridge_cmdline() {
  local cmdline="$1"
  [[ "$cmdline" == *run_websocket_bridge* || "$cmdline" == *run_http_webhook_bridge* ]]
}

gateway_is_gateway_op_cmdline() {
  local cmdline="$1"
  [[ "$cmdline" == *ensure_transport_gateway* \
    || "$cmdline" == *setup_transport_gateway* \
    || "$cmdline" == *stop_transport_gateway* ]]
}

gateway_bridge_owned() {
  local pid="$1"
  local port="${2:-}"
  local run_dir="${3:-}"
  local cmdline=""
  cmdline="$(gateway_pid_cmdline "$pid" || true)"
  if [[ -z "$cmdline" ]]; then
    return 1
  fi
  if ! gateway_is_bridge_cmdline "$cmdline"; then
    return 1
  fi
  # Must be listener on target port OR listed in a pid file of the run dir.
  if [[ -n "$port" ]]; then
    local listener=""
    listener="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
    if [[ "$listener" == "$pid" ]]; then
      return 0
    fi
  fi
  if [[ -n "$run_dir" ]]; then
    local f pid_from_file
    for f in "$run_dir/ws.pid" "$run_dir/http.pid"; do
      if [[ -f "$f" ]]; then
        pid_from_file="$(cat "$f" 2>/dev/null || true)"
        if [[ "$pid_from_file" == "$pid" ]]; then
          return 0
        fi
      fi
    done
  fi
  return 1
}

gateway_tunnel_owned() {
  local pid="$1"
  local run_dir="${2:-$(gateway_run_dir)}"
  local pid_file="$run_dir/cloudflared.pid"
  local file_pid=""
  if [[ -f "$pid_file" ]]; then
    file_pid="$(cat "$pid_file" 2>/dev/null || true)"
  fi
  if [[ "$file_pid" != "$pid" ]]; then
    return 1
  fi
  local cmdline=""
  cmdline="$(gateway_pid_cmdline "$pid" || true)"
  if [[ -z "$cmdline" || "$cmdline" != *cloudflared* ]]; then
    return 1
  fi
  # Match against current env OR stamp (current + previous) so a config change
  # still recognizes the old tunnel as owned during stop/restart.
  if gateway_tunnel_cmdline_matches_identity "$cmdline" \
      "${SOLAR_TUNNEL_MODE:-quick}" \
      "${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}" \
      "${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}" \
      "${SOLAR_HTTP_HOST:-127.0.0.1}" \
      "${SOLAR_HTTP_PORT:-8787}"; then
    return 0
  fi
  if [[ -f "$(gateway_stamp_path)" ]]; then
    local sm sn sc sh sp pm pn pc ph pp
    sm="$(gateway_stamp_get tunnel_mode || true)"
    sn="$(gateway_stamp_get tunnel_name || true)"
    sc="$(gateway_stamp_get tunnel_config || true)"
    sh="$(gateway_stamp_get http_host || true)"
    sp="$(gateway_stamp_get http_port || true)"
    if [[ -n "$sm" ]] && gateway_tunnel_cmdline_matches_identity "$cmdline" "$sm" \
        "${sn:-solar-gateway}" \
        "${sc:-$HOME/.cloudflared/solar-gateway.yml}" \
        "${sh:-127.0.0.1}" \
        "${sp:-8787}"; then
      return 0
    fi
    pm="$(gateway_stamp_get previous_tunnel_mode || true)"
    pn="$(gateway_stamp_get previous_tunnel_name || true)"
    pc="$(gateway_stamp_get previous_tunnel_config || true)"
    ph="$(gateway_stamp_get previous_http_host || true)"
    pp="$(gateway_stamp_get previous_http_port || true)"
    if [[ -n "$pm" ]] && gateway_tunnel_cmdline_matches_identity "$cmdline" "$pm" \
        "${pn:-solar-gateway}" \
        "${pc:-$HOME/.cloudflared/solar-gateway.yml}" \
        "${ph:-127.0.0.1}" \
        "${pp:-8787}"; then
      return 0
    fi
  fi
  return 1
}

gateway_tunnel_cmdline_matches_identity() {
  local cmdline="$1"
  local tunnel_mode="$2"
  local tunnel_name="$3"
  local tunnel_config="$4"
  local host="$5"
  local port="$6"
  if [[ "$tunnel_mode" == "named" ]]; then
    [[ "$cmdline" == *"$tunnel_config"* || "$cmdline" == *"$tunnel_name"* ]]
    return $?
  fi
  [[ "$cmdline" == *"${host}:${port}"* || "$cmdline" == *"http://${host}:${port}"* ]]
}

# ---------------------------------------------------------------------------
# mkdir-lock (portable; no flock)
# ---------------------------------------------------------------------------

_GATEWAY_LOCK_OWNED=0

gateway_acquire_lock() {
  # Internal re-entry when ensure already holds the lock and invokes setup.
  # SOLAR_GATEWAY_LOCK_HELD=1 is honored only if lock/pid exists and belongs
  # to this process's parent (PPID) — spoofing the env alone does not skip acquire.
  if [[ "${SOLAR_GATEWAY_LOCK_HELD:-}" == "1" ]]; then
    transport_gateway_bind_workspace
    gateway_ensure_runtime_dir
    local held_pid=""
    local held_file
    held_file="$(gateway_lock_dir)/pid"
    if [[ -f "$held_file" ]]; then
      held_pid="$(cat "$held_file" 2>/dev/null || true)"
    fi
    if [[ -n "$held_pid" ]] && kill -0 "$held_pid" 2>/dev/null \
      && [[ "$held_pid" == "$PPID" ]]; then
      _GATEWAY_LOCK_OWNED=0
      return 0
    fi
    echo "⚠️  Ignoring SOLAR_GATEWAY_LOCK_HELD (lock not held by parent pid=$PPID)." >&2
    # Fall through to normal acquire.
  fi

  transport_gateway_bind_workspace
  gateway_ensure_runtime_dir
  local lock_dir pid_file existing_pid cmdline
  lock_dir="$(gateway_lock_dir)"
  pid_file="$lock_dir/pid"

  if mkdir "$lock_dir" 2>/dev/null; then
    echo "$$" >"$pid_file"
    _GATEWAY_LOCK_OWNED=1
    return 0
  fi

  if [[ -f "$pid_file" ]]; then
    existing_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
      cmdline="$(gateway_pid_cmdline "$existing_pid" || true)"
      if [[ -z "$cmdline" ]]; then
        # Alive but cmdline unreadable (e.g. sandbox/ps denied) — do not reclaim.
        echo "⏸️  Skipping: another gateway op in progress (pid=$existing_pid)."
        return 1
      fi
      if gateway_is_gateway_op_cmdline "$cmdline"; then
        echo "⏸️  Skipping: another gateway op in progress (pid=$existing_pid)."
        return 1
      fi
      # PID recycled by OS — treat lock as orphan.
      echo "⚠️  Gateway lock pid=$existing_pid is alive but not a gateway op; reclaiming."
    fi
    rm -rf "$lock_dir" 2>/dev/null || true
    if mkdir "$lock_dir" 2>/dev/null; then
      echo "$$" >"$pid_file"
      _GATEWAY_LOCK_OWNED=1
      return 0
    fi
  else
    # Stale lock dir without pid — reclaim.
    rm -rf "$lock_dir" 2>/dev/null || true
    if mkdir "$lock_dir" 2>/dev/null; then
      echo "$$" >"$pid_file"
      _GATEWAY_LOCK_OWNED=1
      return 0
    fi
  fi

  echo "⏸️  Skipping: could not acquire gateway lock."
  return 1
}

gateway_release_lock() {
  if [[ "${_GATEWAY_LOCK_OWNED:-0}" != "1" ]]; then
    return 0
  fi
  local lock_dir
  lock_dir="$(gateway_lock_dir)"
  rm -rf "$lock_dir" 2>/dev/null || true
  _GATEWAY_LOCK_OWNED=0
}

gateway_install_lock_trap() {
  if [[ "${_GATEWAY_LOCK_OWNED:-0}" == "1" ]]; then
    trap 'gateway_release_lock' EXIT INT TERM
  fi
}

# ---------------------------------------------------------------------------
# Telegram webhook (boolean; OWNER is migration-only)
# ---------------------------------------------------------------------------

_gateway_trim_lower() {
  printf '%s' "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]'
}

# Effective claim: true | false | "" (absent). Only true may call setWebhook.
# Reads SOLAR_GATEWAY_CLAIM_TELEGRAM only. No OWNER / SOLAR_TELEGRAM_WEBHOOK fallback.
gateway_telegram_claim() {
  printf '%s' "$(_gateway_trim_lower "${SOLAR_GATEWAY_CLAIM_TELEGRAM:-}")"
}

gateway_telegram_claim_label() {
  local flag
  flag="$(gateway_telegram_claim)"
  if [[ -z "$flag" ]]; then
    printf '%s' "absent"
  else
    printf '%s' "$flag"
  fi
}

# 0 if claim is usable by setup: true, false, or absent. Any other value → 1.
gateway_telegram_claim_valid() {
  local flag
  flag="$(gateway_telegram_claim)"
  [[ -z "$flag" || "$flag" == "true" || "$flag" == "false" ]]
}

# HTTP routes mounted under SOLAR_HTTP_WEBHOOK_BASE. telegram only if a bot token exists.
gateway_http_channels_label() {
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    printf '%s' "n8n, telegram"
  else
    printf '%s' "n8n"
  fi
}

gateway_telegram_expected_url() {
  local base="" base_path
  if [[ -n "${SOLAR_CLOUDFLARED_HOSTNAME:-}" && "${SOLAR_CLOUDFLARED_HOSTNAME:-}" != "REPLACE_ME" ]]; then
    base="https://${SOLAR_CLOUDFLARED_HOSTNAME}"
  fi
  if [[ -z "$base" ]]; then
    return 1
  fi
  base_path="${SOLAR_HTTP_WEBHOOK_BASE:-/webhook}"
  printf '%s' "${base}${base_path%/}/telegram"
}

gateway_telegram_live_url() {
  local info_json
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    return 1
  fi
  info_json="$(curl -fsS --connect-timeout 5 --max-time 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo")" || return 1
  printf '%s' "$info_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
result = data.get("result")
if data.get("ok") is not True or not isinstance(result, dict) or not isinstance(result.get("url"), str):
    sys.exit(1)
print(result["url"])
'
}

# setup/ensure: never roll back the gateway because a foreign webhook exists.
# Returns 1 only when claim=true and setWebhook/verify of Solar's URL fails.
gateway_telegram_lifecycle_setup() {
  local flag live expected
  flag="$(gateway_telegram_claim)"
  if ! gateway_telegram_claim_valid; then
    echo "preflight: invalid SOLAR_GATEWAY_CLAIM_TELEGRAM=${SOLAR_GATEWAY_CLAIM_TELEGRAM:-} (expected true|false or absent)" >&2
    return 1
  fi
  expected="$(gateway_telegram_expected_url || true)"
  live=""
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    if ! live="$(gateway_telegram_live_url)"; then
      echo "Telegram webhook ownership could not be verified; skipping setWebhook." >&2
      return 0
    fi
  fi

  if [[ "$flag" != "true" ]]; then
    if [[ "$flag" == "false" ]]; then
      echo "SOLAR_GATEWAY_CLAIM_TELEGRAM=false — skipping setWebhook."
    else
      echo "SOLAR_GATEWAY_CLAIM_TELEGRAM unset — not claiming."
    fi
    return 0
  fi

  if [[ -n "$live" && -n "$expected" && "$live" != "$expected" ]]; then
    echo "Telegram webhook already points elsewhere — not claiming it."
    echo "Do not set SOLAR_GATEWAY_CLAIM_TELEGRAM=true while a foreign URL is live."
    return 0
  fi

  if [[ "${SOLAR_GATEWAY_FORCE_TELEGRAM_FAIL:-}" == "1" ]]; then
    echo "SOLAR_GATEWAY_FORCE_TELEGRAM_FAIL=1 — simulating setWebhook failure." >&2
    return 1
  fi
  bash "$(transport_gateway_script set_telegram_webhook.sh)" || return 1
  bash "$(transport_gateway_script verify_telegram_webhook.sh)" || return 1
  return 0
}

gateway_n8n_webhook_secret_sha256() {
  local secret="${SOLAR_N8N_WEBHOOK_SECRET:-}"
  if [[ -z "$secret" ]]; then
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$secret" | shasum -a 256 | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$secret" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$secret" | cksum | awk '{print $1}'
  fi
}

# ---------------------------------------------------------------------------
# Fingerprint / stamp / fail
# ---------------------------------------------------------------------------

gateway_fingerprint_keys_static() {
  cat <<'EOF'
SOLAR_ROUTER_PROVIDER_PRIORITY
SOLAR_AI_PROVIDER_PRIORITY
SOLAR_ROUTER_TIMEOUT_SEC
SOLAR_ROUTER_SYSTEM_PROMPT_FILE
SOLAR_ROUTER_RUNTIME_DIR
SOLAR_ROUTER_CONTEXT_TURNS
SOLAR_ROUTER_LOG_PROMPTS
SOLAR_WS_HOST
SOLAR_WS_PORT
SOLAR_WS_PATH
SOLAR_HTTP_HOST
SOLAR_HTTP_PORT
SOLAR_HTTP_WEBHOOK_BASE
SOLAR_HTTP_WEBHOOK_PATH
SOLAR_GATEWAY_RUN_DIR
SOLAR_TUNNEL_MODE
SOLAR_CLOUDFLARED_TUNNEL_NAME
SOLAR_CLOUDFLARED_HOSTNAME
SOLAR_CLOUDFLARED_CONFIG
SOLAR_GATEWAY_CLAIM_TELEGRAM
EOF
}

gateway_collect_fingerprint_material() {
  transport_gateway_bind_workspace
  local key val lines="" secret_fp=""
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    eval "val=\${$key:-}"
    lines+="${key}=${val}"$'\n'
  done < <(gateway_fingerprint_keys_static)

  # Include any SOLAR_ROUTER_*_CMD from environment (allowlist pattern).
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    eval "val=\${$key:-}"
    lines+="${key}=${val}"$'\n'
  done < <( (compgen -e 2>/dev/null || true) | grep -E '^SOLAR_ROUTER_[A-Z0-9]+_CMD$' | sort || true)

  # Derived: hash of n8n webhook secret (never plaintext). Empty when unset.
  secret_fp="$(gateway_n8n_webhook_secret_sha256 || true)"
  lines+="SOLAR_N8N_WEBHOOK_SECRET_SHA256=${secret_fp}"$'\n'

  printf '%s' "$lines" | sort
}

gateway_compute_fingerprint() {
  local material hash
  material="$(gateway_collect_fingerprint_material)"
  if command -v shasum >/dev/null 2>&1; then
    hash="$(printf '%s' "$material" | shasum -a 256 | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    hash="$(printf '%s' "$material" | sha256sum | awk '{print $1}')"
  else
    hash="$(printf '%s' "$material" | cksum | awk '{print $1}')"
  fi
  printf '%s' "$hash"
}

gateway_stamp_get() {
  local key="$1"
  local stamp
  stamp="$(gateway_stamp_path)"
  if [[ ! -f "$stamp" ]]; then
    return 1
  fi
  grep -E "^${key}=" "$stamp" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

gateway_write_stamp() {
  transport_gateway_bind_workspace
  gateway_ensure_runtime_dir
  local stamp tmp run_dir ws_port http_port fp now prev_run prev_ws prev_http
  local tunnel_mode tunnel_name tunnel_config http_host
  local prev_tm prev_tn prev_tc prev_hh
  stamp="$(gateway_stamp_path)"
  tmp="${stamp}.tmp.$$"
  run_dir="$(gateway_run_dir)"
  ws_port="$(gateway_ws_port)"
  http_port="$(gateway_http_port)"
  http_host="${SOLAR_HTTP_HOST:-127.0.0.1}"
  tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
  tunnel_name="${SOLAR_CLOUDFLARED_TUNNEL_NAME:-solar-gateway}"
  tunnel_config="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
  fp="$(gateway_compute_fingerprint)"
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  prev_run="$(gateway_stamp_get run_dir 2>/dev/null || true)"
  prev_ws="$(gateway_stamp_get ws_port 2>/dev/null || true)"
  prev_http="$(gateway_stamp_get http_port 2>/dev/null || true)"
  prev_tm="$(gateway_stamp_get tunnel_mode 2>/dev/null || true)"
  prev_tn="$(gateway_stamp_get tunnel_name 2>/dev/null || true)"
  prev_tc="$(gateway_stamp_get tunnel_config 2>/dev/null || true)"
  prev_hh="$(gateway_stamp_get http_host 2>/dev/null || true)"
  if [[ -z "$prev_run" ]]; then
    prev_run="$run_dir"
  fi
  if [[ -z "$prev_ws" ]]; then
    prev_ws="$ws_port"
  fi
  if [[ -z "$prev_http" ]]; then
    prev_http="$http_port"
  fi
  if [[ -z "$prev_tm" ]]; then
    prev_tm="$tunnel_mode"
  fi
  if [[ -z "$prev_tn" ]]; then
    prev_tn="$tunnel_name"
  fi
  if [[ -z "$prev_tc" ]]; then
    prev_tc="$tunnel_config"
  fi
  if [[ -z "$prev_hh" ]]; then
    prev_hh="$http_host"
  fi

  cat >"$tmp" <<EOF
fingerprint=$fp
updated_at=$now
run_dir=$run_dir
ws_port=$ws_port
http_port=$http_port
http_host=$http_host
tunnel_mode=$tunnel_mode
tunnel_name=$tunnel_name
tunnel_config=$tunnel_config
ws_pid_path=$run_dir/ws.pid
http_pid_path=$run_dir/http.pid
cloudflared_pid_path=$run_dir/cloudflared.pid
previous_run_dir=$prev_run
previous_ws_port=$prev_ws
previous_http_port=$prev_http
previous_http_host=$prev_hh
previous_tunnel_mode=$prev_tm
previous_tunnel_name=$prev_tn
previous_tunnel_config=$prev_tc
keys_present=$(gateway_collect_fingerprint_material | awk -F= 'NF && $2!=""{print $1}' | paste -sd, -)
EOF
  if command -v fsync >/dev/null 2>&1; then
    fsync "$tmp" 2>/dev/null || true
  elif command -v sync >/dev/null 2>&1; then
    sync "$tmp" 2>/dev/null || true
  fi
  mv -f "$tmp" "$stamp"
  rm -f "$(gateway_fail_path)"
}

gateway_write_env_fail() {
  local reason="${1:-preflight_or_setup_failed}"
  transport_gateway_bind_workspace
  gateway_ensure_runtime_dir
  local fail_path fp now attempts next_delay next_at last_fp last_attempts shift_amt exhausted
  fail_path="$(gateway_fail_path)"
  fp="$(gateway_compute_fingerprint)"
  now="$(date +%s)"
  attempts=1
  if [[ -f "$fail_path" ]]; then
    last_fp="$(grep -E '^fingerprint=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
    last_attempts="$(grep -E '^attempts=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
    if [[ "$last_fp" == "$fp" && -n "$last_attempts" ]]; then
      attempts=$((last_attempts + 1))
    fi
  fi
  exhausted=0
  if (( attempts >= GATEWAY_FAIL_ATTEMPTS_CAP )); then
    exhausted=1
    # Far-future retry marker; ensure stops until fingerprint changes.
    next_at=$((now + 86400 * 365))
  else
    shift_amt=$((attempts - 1))
    if (( shift_amt > 16 )); then
      shift_amt=16
    fi
    next_delay=$((GATEWAY_BACKOFF_BASE_SEC * (1 << shift_amt)))
    if (( next_delay > GATEWAY_BACKOFF_CAP_SEC )); then
      next_delay=$GATEWAY_BACKOFF_CAP_SEC
    fi
    next_at=$((now + next_delay))
  fi
  local tmp="${fail_path}.tmp.$$"
  cat >"$tmp" <<EOF
fingerprint=$fp
failed_at=$now
attempts=$attempts
next_retry_at=$next_at
exhausted=$exhausted
reason=$reason
EOF
  mv -f "$tmp" "$fail_path"
}

gateway_fail_exhausted() {
  local fail_path fp fail_fp attempts exhausted
  fail_path="$(gateway_fail_path)"
  if [[ ! -f "$fail_path" ]]; then
    return 1
  fi
  fp="$(gateway_compute_fingerprint)"
  fail_fp="$(grep -E '^fingerprint=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  if [[ "$fail_fp" != "$fp" ]]; then
    return 1
  fi
  exhausted="$(grep -E '^exhausted=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  if [[ "$exhausted" == "1" ]]; then
    return 0
  fi
  attempts="$(grep -E '^attempts=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  if [[ -n "$attempts" ]] && (( attempts >= GATEWAY_FAIL_ATTEMPTS_CAP )); then
    return 0
  fi
  return 1
}

gateway_backoff_active() {
  local fail_path fp now next_at fail_fp
  fail_path="$(gateway_fail_path)"
  if [[ ! -f "$fail_path" ]]; then
    return 1
  fi
  fp="$(gateway_compute_fingerprint)"
  fail_fp="$(grep -E '^fingerprint=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  if [[ "$fail_fp" != "$fp" ]]; then
    # Fingerprint changed — reset backoff.
    return 1
  fi
  # Hard stop after attempt cap (same fingerprint).
  if gateway_fail_exhausted; then
    return 0
  fi
  next_at="$(grep -E '^next_retry_at=' "$fail_path" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  now="$(date +%s)"
  if [[ -n "$next_at" ]] && (( now < next_at )); then
    return 0
  fi
  return 1
}

gateway_solar_bridges_alive() {
  local run_dir port pid cmdline
  run_dir="$(gateway_run_dir)"
  for port in "$(gateway_ws_port)" "$(gateway_http_port)"; do
    pid="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
    if [[ -n "$pid" ]]; then
      cmdline="$(gateway_pid_cmdline "$pid" || true)"
      if gateway_is_bridge_cmdline "$cmdline"; then
        return 0
      fi
    fi
  done
  # Also check pid files even if port moved.
  local f
  for f in "$run_dir/ws.pid" "$run_dir/http.pid"; do
    if [[ -f "$f" ]]; then
      pid="$(cat "$f" 2>/dev/null || true)"
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        cmdline="$(gateway_pid_cmdline "$pid" || true)"
        if gateway_is_bridge_cmdline "$cmdline"; then
          return 0
        fi
      fi
    fi
  done
  return 1
}

gateway_has_drift() {
  local stamp fp stamped
  stamp="$(gateway_stamp_path)"
  fp="$(gateway_compute_fingerprint)"
  if [[ ! -f "$stamp" ]]; then
    if gateway_solar_bridges_alive; then
      return 0
    fi
    return 1
  fi
  stamped="$(gateway_stamp_get fingerprint || true)"
  if [[ "$stamped" != "$fp" ]]; then
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# Supported providers (canonical solar-router)
# ---------------------------------------------------------------------------

gateway_list_supported_providers() {
  bash "$(transport_gateway_router_script list_supported_providers.sh)" 2>/dev/null
}

gateway_first_provider_binary() {
  local priority first router_scripts
  priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-codex,claude,agy,agent}}"
  first="$(printf '%s' "$priority" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' | head -n1 | tr '[:upper:]' '[:lower:]')"
  if [[ -z "$first" ]]; then
    return 1
  fi
  # Prefer explicit CMD override; else default binary name == provider id (matches provider modules).
  local cmd_key="SOLAR_ROUTER_$(printf '%s' "$first" | tr '[:lower:]' '[:upper:]')_CMD"
  local raw=""
  eval "raw=\${$cmd_key:-}"
  if [[ -z "$raw" ]]; then
    # Legacy SOLAR_AI_*_CMD
    local legacy="SOLAR_AI_$(printf '%s' "$first" | tr '[:lower:]' '[:upper:]')_CMD"
    eval "raw=\${$legacy:-}"
  fi
  if [[ -n "$raw" ]]; then
    # First token of the command string
    printf '%s' "$raw" | awk '{print $1; exit}'
    return 0
  fi
  # Canonical default: provider id is the CLI name (claude/codex/agy/agent/ollama).
  # Cross-check provider is registered before returning.
  if ! gateway_list_supported_providers | grep -qx "$first"; then
    return 1
  fi
  printf '%s' "$first"
}

# ---------------------------------------------------------------------------
# Preflight (non-destructive)
# ---------------------------------------------------------------------------

gateway_preflight() {
  local err=0
  local msg=""

  transport_gateway_bind_workspace

  if [[ ! -f "$SOLAR_WORKSPACE/.env" ]]; then
    echo "preflight: missing .env" >&2
    return 1
  fi

  # Parseable allowlist / fingerprint
  if ! gateway_compute_fingerprint >/dev/null; then
    echo "preflight: failed to compute fingerprint" >&2
    return 1
  fi

  # Telegram claim: true|false or absent. No OWNER / SOLAR_TELEGRAM_WEBHOOK fallback.
  if ! gateway_telegram_claim_valid; then
    echo "preflight: invalid SOLAR_GATEWAY_CLAIM_TELEGRAM=${SOLAR_GATEWAY_CLAIM_TELEGRAM:-} (expected true|false or absent)" >&2
    err=1
  fi

  # Provider tokens ⊆ supported set
  local priority token supported
  priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-}}"
  if [[ -n "$priority" ]]; then
    supported="$(gateway_list_supported_providers | tr '\n' ' ')"
    # bash 3.2 portable: split on commas via tr
    while IFS= read -r token; do
      token="$(echo "$token" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')"
      [[ -z "$token" ]] && continue
      if ! printf '%s' " $supported " | grep -qw "$token"; then
        echo "preflight: unsupported provider token: $token" >&2
        err=1
      fi
    done < <(printf '%s' "$priority" | tr ',' '\n')
  fi

  # Ports valid
  local ws_port http_port
  ws_port="$(gateway_ws_port)"
  http_port="$(gateway_http_port)"
  if ! [[ "$ws_port" =~ ^[0-9]+$ ]] || (( ws_port < 1 || ws_port > 65535 )); then
    echo "preflight: invalid SOLAR_WS_PORT=$ws_port" >&2
    err=1
  fi
  if ! [[ "$http_port" =~ ^[0-9]+$ ]] || (( http_port < 1 || http_port > 65535 )); then
    echo "preflight: invalid SOLAR_HTTP_PORT=$http_port" >&2
    err=1
  fi

  # If ports change vs stamp, new ports must not be held by foreign listeners.
  local stamped_ws stamped_http pid cmdline
  stamped_ws="$(gateway_stamp_get ws_port 2>/dev/null || true)"
  stamped_http="$(gateway_stamp_get http_port 2>/dev/null || true)"
  if [[ -n "$stamped_ws" && "$stamped_ws" != "$ws_port" ]]; then
    pid="$(gateway_listener_pid_for_port "$ws_port" 2>/dev/null || true)"
    if [[ -n "$pid" ]]; then
      cmdline="$(gateway_pid_cmdline "$pid" || true)"
      if ! gateway_is_bridge_cmdline "$cmdline"; then
        echo "preflight: new WS port $ws_port held by foreign pid $pid" >&2
        err=1
      fi
    fi
  fi
  if [[ -n "$stamped_http" && "$stamped_http" != "$http_port" ]]; then
    pid="$(gateway_listener_pid_for_port "$http_port" 2>/dev/null || true)"
    if [[ -n "$pid" ]]; then
      cmdline="$(gateway_pid_cmdline "$pid" || true)"
      if ! gateway_is_bridge_cmdline "$cmdline"; then
        echo "preflight: new HTTP port $http_port held by foreign pid $pid" >&2
        err=1
      fi
    fi
  fi

  # Named tunnel config
  local tunnel_mode="${SOLAR_TUNNEL_MODE:-quick}"
  if [[ "$tunnel_mode" == "named" ]]; then
    local tunnel_config="${SOLAR_CLOUDFLARED_CONFIG:-$HOME/.cloudflared/solar-gateway.yml}"
    local tunnel_hostname="${SOLAR_CLOUDFLARED_HOSTNAME:-REPLACE_ME}"
    if [[ ! -f "$tunnel_config" ]]; then
      echo "preflight: missing named tunnel config: $tunnel_config" >&2
      err=1
    fi
    if [[ "$tunnel_hostname" == "REPLACE_ME" || -z "$tunnel_hostname" ]]; then
      echo "preflight: SOLAR_CLOUDFLARED_HOSTNAME not configured" >&2
      err=1
    fi
  fi

  # stop --dry-run must not report foreign blockers (would_force needed)
  local dry_out
  set +e
  dry_out="$(bash "$(transport_gateway_script stop_transport_gateway.sh)" --dry-run 2>&1)"
  set -e
  if printf '%s' "$dry_out" | grep -q 'action=skip'; then
    # skip of foreign while target still occupied is a blocker
    if printf '%s' "$dry_out" | grep -q 'foreign=true'; then
      local still_blocked=0
      if ! gateway_port_is_free "$(gateway_ws_port)"; then still_blocked=1; fi
      if ! gateway_port_is_free "$(gateway_http_port)"; then still_blocked=1; fi
      # Also check previous ports from stamp
      local prev_ws prev_http
      prev_ws="$(gateway_stamp_get previous_ws_port 2>/dev/null || gateway_stamp_get ws_port 2>/dev/null || true)"
      prev_http="$(gateway_stamp_get previous_http_port 2>/dev/null || gateway_stamp_get http_port 2>/dev/null || true)"
      if [[ -n "$prev_ws" ]] && ! gateway_port_is_free "$prev_ws"; then
        pid="$(gateway_listener_pid_for_port "$prev_ws" 2>/dev/null || true)"
        cmdline="$(gateway_pid_cmdline "$pid" || true)"
        if [[ -n "$pid" ]] && ! gateway_is_bridge_cmdline "$cmdline"; then
          still_blocked=1
        fi
      fi
      if [[ -n "$prev_http" ]] && ! gateway_port_is_free "$prev_http"; then
        pid="$(gateway_listener_pid_for_port "$prev_http" 2>/dev/null || true)"
        cmdline="$(gateway_pid_cmdline "$pid" || true)"
        if [[ -n "$pid" ]] && ! gateway_is_bridge_cmdline "$cmdline"; then
          still_blocked=1
        fi
      fi
      if (( still_blocked )); then
        echo "preflight: stop --dry-run reports foreign blockers; need --force" >&2
        err=1
      fi
    fi
  fi

  # First provider binary exists (existence only)
  local bin=""
  set +e
  bin="$(gateway_first_provider_binary 2>/dev/null)"
  set -e
  if [[ -z "$bin" ]]; then
    echo "preflight: could not resolve first provider binary" >&2
    err=1
  elif ! command -v "$bin" >/dev/null 2>&1; then
    echo "preflight: provider binary not in PATH: $bin" >&2
    err=1
  fi

  return "$err"
}

gateway_runtime_healthy_local() {
  # Lightweight local healthy check (bridges + /health) without full check script.
  local run_dir ws_port http_port host
  run_dir="$(gateway_run_dir)"
  ws_port="$(gateway_ws_port)"
  http_port="$(gateway_http_port)"
  host="${SOLAR_HTTP_HOST:-127.0.0.1}"
  local ws_ok=0 http_ok=0
  if gateway_solar_bridges_alive; then
    ws_ok=1
    http_ok=1
  fi
  local body=""
  body="$(curl -fsS --max-time 3 "http://${host}:${http_port}/health" 2>/dev/null || true)"
  if [[ "$body" == *"\"bridge\": \"solar-transport-gateway\""* && "$ws_ok" == 1 && "$http_ok" == 1 ]]; then
    return 0
  fi
  return 1
}
