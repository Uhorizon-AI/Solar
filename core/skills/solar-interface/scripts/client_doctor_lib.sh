#!/usr/bin/env bash
# client_doctor_lib.sh — shared workspace checks (doctor + solar status).
# Expects: SOLAR_WORKSPACE, SOLAR_ROOT; optional .env already sourced.

_solar_client_port_listener_pid() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null | head -n 1
}

_solar_client_process_args() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" -ww -o args= 2>/dev/null || ps -p "$pid" -o command= 2>/dev/null || true
}

_solar_client_is_interface_port() {
  local port="$1"
  local pid="$2"
  local lib_dir="${SOLAR_CLIENT_SCRIPT_DIR:-}"
  if [[ -f "${lib_dir}/interface_lib.sh" ]]; then
    # shellcheck source=interface_lib.sh
    source "${lib_dir}/interface_lib.sh"
    if is_interface_server_pid "$pid"; then
      return 0
    fi
    if command -v curl >/dev/null 2>&1; then
      curl -fsS --max-time 2 "http://${SOLAR_INTERFACE_HOST:-127.0.0.1}:${port}/ready" >/dev/null 2>&1
      return $?
    fi
  fi
  return 1
}

_solar_client_is_http_port() {
  local port="$1"
  local pid="$2"
  local host="${SOLAR_HTTP_HOST:-127.0.0.1}"
  local gw_run_dir="${SOLAR_GATEWAY_RUN_DIR:-/tmp/solar-transport-gateway}"

  if command -v curl >/dev/null 2>&1; then
    local body
    body="$(curl -fsS --max-time 2 "http://${host}:${port}/health" 2>/dev/null || true)"
    if [[ "$body" == *"solar-transport-gateway"* ]]; then
      return 0
    fi
  fi

  if [[ -f "$gw_run_dir/http.pid" ]]; then
    local recorded
    recorded="$(tr -d '[:space:]' <"$gw_run_dir/http.pid" 2>/dev/null || true)"
    if [[ -n "$recorded" && "$recorded" == "$pid" ]]; then
      return 0
    fi
  fi

  local args
  args="$(_solar_client_process_args "$pid")"
  [[ "$args" == *"run_http_webhook_bridge"* ]] || [[ "$args" == *"solar-transport-gateway"* ]]
}

# Sets SOLAR_CLIENT_GOV_MSG; returns 0 if OK, 1 if WARN.
solar_client_check_governance_symlinks() {
  SOLAR_CLIENT_GOV_MSG=""
  local issues=()
  local f
  for f in CLAUDE.md GEMINI.md .cursorrules; do
    if [[ -L "$SOLAR_WORKSPACE/$f" ]]; then
      continue
    fi
    if [[ -f "$SOLAR_WORKSPACE/$f" ]] && grep -q "symlink unavailable" "$SOLAR_WORKSPACE/$f" 2>/dev/null; then
      issues+=("$f stub")
    elif [[ -f "$SOLAR_WORKSPACE/$f" ]]; then
      issues+=("$f not symlink")
    fi
  done
  if [[ ${#issues[@]} -gt 0 ]]; then
    SOLAR_CLIENT_GOV_MSG="${issues[*]}"
    return 1
  fi
  return 0
}

# Sets SOLAR_CLIENT_PORTS_MSG; returns 0 if OK, 1 if WARN.
solar_client_check_ports() {
  SOLAR_CLIENT_PORTS_MSG=""
  local issues=()
  local var port pid
  for var in SOLAR_INTERFACE_PORT SOLAR_HTTP_PORT; do
    port="${!var:-}"
    [[ -n "$port" ]] || continue
    pid="$(_solar_client_port_listener_pid "$port" || true)"
    [[ -n "$pid" ]] || continue
    case "$var" in
      SOLAR_INTERFACE_PORT)
        if ! _solar_client_is_interface_port "$port" "$pid"; then
          issues+=("$var=$port foreign pid $pid")
        fi
        ;;
      SOLAR_HTTP_PORT)
        if ! _solar_client_is_http_port "$port" "$pid"; then
          issues+=("$var=$port foreign pid $pid")
        fi
        ;;
    esac
  done
  if [[ ${#issues[@]} -gt 0 ]]; then
    SOLAR_CLIENT_PORTS_MSG="${issues[*]}"
    return 1
  fi
  return 0
}
