#!/usr/bin/env bash
# Stop Solar transport gateway processes with strict ownership.
#
# Usage:
#   bash .../stop_transport_gateway.sh [--dry-run] [--force] [--tunnel-only]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=transport_gateway_lib.sh
source "$SCRIPT_DIR/transport_gateway_lib.sh"
transport_gateway_bind_workspace

DRY_RUN=false
FORCE=false
TUNNEL_ONLY=false

usage() {
  cat <<EOF
Usage:
  bash $(transport_gateway_script stop_transport_gateway.sh) [--dry-run] [--force] [--tunnel-only]

Options:
  --dry-run       Report actions without killing or unlinking
  --force         Kill foreign listeners that block target ports
  --tunnel-only   Only stop cloudflared (skip bridges)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --force) FORCE=true; shift ;;
    --tunnel-only) TUNNEL_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# Collect unique run dirs and ports (current env + stamp previous/current).
RUN_DIRS=""
WS_PORTS=""
HTTP_PORTS=""

_list_has() {
  local haystack="$1"
  local needle="$2"
  case " $haystack " in
    *" $needle "*) return 0 ;;
    *) return 1 ;;
  esac
}

_list_add() {
  # usage: _list_add VARNAME value
  local var="$1"
  local val="$2"
  local cur
  [[ -z "$val" ]] && return 0
  eval "cur=\${$var}"
  if _list_has "$cur" "$val"; then
    return 0
  fi
  if [[ -z "$cur" ]]; then
    eval "$var=\"\$val\""
  else
    eval "$var=\"\$cur \$val\""
  fi
}

_list_add RUN_DIRS "$(gateway_run_dir)"
_list_add WS_PORTS "$(gateway_ws_port)"
_list_add HTTP_PORTS "$(gateway_http_port)"

if [[ -f "$(gateway_stamp_path)" ]]; then
  _list_add RUN_DIRS "$(gateway_stamp_get run_dir || true)"
  _list_add RUN_DIRS "$(gateway_stamp_get previous_run_dir || true)"
  _list_add WS_PORTS "$(gateway_stamp_get ws_port || true)"
  _list_add WS_PORTS "$(gateway_stamp_get previous_ws_port || true)"
  _list_add HTTP_PORTS "$(gateway_stamp_get http_port || true)"
  _list_add HTTP_PORTS "$(gateway_stamp_get previous_http_port || true)"
fi

report_action() {
  local pid="$1" action="$2" kind="$3" ports="$4" owned="$5" foreign="$6" cmd_short="${7:-}"
  local priority=""
  if [[ "$owned" == "true" && "$kind" == "bridge" ]]; then
    priority="${SOLAR_ROUTER_PROVIDER_PRIORITY:-${SOLAR_AI_PROVIDER_PRIORITY:-}}"
  fi
  printf 'pid=%s action=%s kind=%s ports=%s owned=%s foreign=%s' \
    "$pid" "$action" "$kind" "$ports" "$owned" "$foreign"
  if [[ -n "$cmd_short" ]]; then
    printf ' cmd=%s' "$cmd_short"
  fi
  if [[ -n "$priority" ]]; then
    printf ' priority=%s' "$priority"
  fi
  printf '\n'
}

kill_pid_sequence() {
  local pid="$1"
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  kill -TERM "$pid" 2>/dev/null || true
  local i
  for i in 1 2 3 4 5; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.4
  done
  kill -KILL "$pid" 2>/dev/null || true
  sleep 0.2
}

short_cmd() {
  local cmdline="$1"
  printf '%s' "$cmdline" | awk '{print $1,$2,$3}' | cut -c1-80
}

SEEN_PIDS=" "
EXIT_CODE=0

consider_pid() {
  local pid="$1" kind="$2" ports="$3" run_dir="$4"
  [[ -z "$pid" ]] && return 0
  if _list_has "$SEEN_PIDS" "$pid"; then
    return 0
  fi
  SEEN_PIDS="$SEEN_PIDS $pid "

  local cmdline owned=false foreign=false action p
  cmdline="$(gateway_pid_cmdline "$pid" 2>/dev/null || true)"
  if [[ -z "$cmdline" ]]; then
    return 0
  fi

  if [[ "$kind" == "bridge" ]]; then
    for p in $ports; do
      if gateway_bridge_owned "$pid" "$p" "$run_dir"; then
        owned=true
        break
      fi
    done
    if [[ "$owned" != true ]]; then
      if gateway_bridge_owned "$pid" "" "$run_dir"; then
        owned=true
      fi
    fi
  elif [[ "$kind" == "tunnel" ]]; then
    if gateway_tunnel_owned "$pid" "$run_dir"; then
      owned=true
    fi
  fi

  if [[ "$owned" != true ]]; then
    foreign=true
  fi

  if [[ "$owned" == true ]]; then
    action="kill"
    report_action "$pid" "$action" "$kind" "$ports" true false "$(short_cmd "$cmdline")"
    kill_pid_sequence "$pid"
  elif [[ "$FORCE" == true ]]; then
    action="force_kill"
    report_action "$pid" "$action" "$kind" "$ports" false true "$(short_cmd "$cmdline")"
    kill_pid_sequence "$pid"
  else
    action="skip"
    report_action "$pid" "$action" "$kind" "$ports" false true "$(short_cmd "$cmdline")"
    EXIT_CODE=1
  fi
}

# --- Bridges ---
if [[ "$TUNNEL_ONLY" != true ]]; then
  for local_rd in $RUN_DIRS; do
    [[ -z "$local_rd" ]] && continue
    for pf in "$local_rd/ws.pid" "$local_rd/http.pid"; do
      if [[ -f "$pf" ]]; then
        pid="$(cat "$pf" 2>/dev/null || true)"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
          if [[ "$pf" == *ws.pid ]]; then
            port_hint="$(gateway_ws_port)"
          else
            port_hint="$(gateway_http_port)"
          fi
          consider_pid "$pid" "bridge" "$port_hint" "$local_rd"
        fi
      fi
    done
  done

  for port in $WS_PORTS $HTTP_PORTS; do
    [[ -z "$port" ]] && continue
    pid="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
    if [[ -n "$pid" ]]; then
      match_rd="$(echo "$RUN_DIRS" | awk '{print $1}')"
      for local_rd in $RUN_DIRS; do
        for pf in "$local_rd/ws.pid" "$local_rd/http.pid"; do
          if [[ -f "$pf" ]] && [[ "$(cat "$pf" 2>/dev/null || true)" == "$pid" ]]; then
            match_rd="$local_rd"
          fi
        done
      done
      consider_pid "$pid" "bridge" "$port" "$match_rd"
    fi
  done
fi

# --- Tunnel (pid file + cmdline only; no global cloudflared scan) ---
for local_rd in $RUN_DIRS; do
  [[ -z "$local_rd" ]] && continue
  if [[ -f "$local_rd/cloudflared.pid" ]]; then
    pid="$(cat "$local_rd/cloudflared.pid" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      consider_pid "$pid" "tunnel" "-" "$local_rd"
    fi
  fi
done

# --- Stale pid file unlink ---
unlink_stale_pid() {
  local pid_file="$1" port="${2:-}"
  [[ -f "$pid_file" ]] || return 0
  local pid owned=false cmdline listener lcmd rd
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    cmdline="$(gateway_pid_cmdline "$pid" || true)"
    if [[ "$pid_file" == *cloudflared.pid ]]; then
      rd="$(dirname "$pid_file")"
      if gateway_tunnel_owned "$pid" "$rd"; then
        owned=true
      fi
    else
      if gateway_is_bridge_cmdline "$cmdline"; then
        if [[ -n "$port" ]] && gateway_bridge_owned "$pid" "$port" "$(dirname "$pid_file")"; then
          owned=true
        elif gateway_bridge_owned "$pid" "" "$(dirname "$pid_file")"; then
          owned=true
        fi
      fi
    fi
    if [[ "$owned" == true ]]; then
      return 0
    fi
    # Live but not owned
    if [[ -n "$port" ]] && ! gateway_port_is_free "$port"; then
      listener="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
      if [[ -n "$listener" ]]; then
        lcmd="$(gateway_pid_cmdline "$listener" || true)"
        if ! gateway_is_bridge_cmdline "$lcmd"; then
          report_action "$pid" "skip" "pidfile" "${port:--}" false true "stale_but_port_busy"
          EXIT_CODE=1
          return 0
        fi
      fi
    fi
  else
    # Dead pid — unlink if port free (or no port / owned bridge)
    if [[ -n "$port" ]] && ! gateway_port_is_free "$port"; then
      listener="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
      if [[ -n "$listener" ]]; then
        lcmd="$(gateway_pid_cmdline "$listener" || true)"
        if ! gateway_is_bridge_cmdline "$lcmd"; then
          report_action "${pid:-0}" "skip" "pidfile" "$port" false true "dead_pid_port_busy_foreign"
          EXIT_CODE=1
          return 0
        fi
      fi
    fi
  fi

  report_action "${pid:-0}" "unlink_stale_pid" "pidfile" "${port:--}" false false "$(basename "$pid_file")"
  if [[ "$DRY_RUN" != true ]]; then
    rm -f "$pid_file"
  fi
}

for local_rd in $RUN_DIRS; do
  [[ -z "$local_rd" ]] && continue
  if [[ "$TUNNEL_ONLY" != true ]]; then
    unlink_stale_pid "$local_rd/ws.pid" "$(gateway_ws_port)"
    unlink_stale_pid "$local_rd/http.pid" "$(gateway_http_port)"
  fi
  unlink_stale_pid "$local_rd/cloudflared.pid" ""
done

# Final: if targets still occupied by foreign without force, fail.
if [[ "$FORCE" != true && "$DRY_RUN" != true ]]; then
  if [[ "$TUNNEL_ONLY" != true ]]; then
    for port in $WS_PORTS $HTTP_PORTS; do
      [[ -z "$port" ]] && continue
      pid="$(gateway_listener_pid_for_port "$port" 2>/dev/null || true)"
      if [[ -n "$pid" ]]; then
        cmdline="$(gateway_pid_cmdline "$pid" || true)"
        if ! gateway_is_bridge_cmdline "$cmdline"; then
          echo "❌ Port $port still occupied by foreign pid $pid" >&2
          EXIT_CODE=1
        fi
      fi
    done
  fi
fi

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry-run complete."
fi

exit "$EXIT_CODE"
