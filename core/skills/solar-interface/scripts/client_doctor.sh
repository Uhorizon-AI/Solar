#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_solar_home.sh
source "$SCRIPT_DIR/resolve_solar_home.sh"
solar_resolve_home --quiet

warn_count=0
err_count=0

warn() { echo "WARN: $1"; warn_count=$((warn_count + 1)); }
err() { echo "ERROR: $1"; err_count=$((err_count + 1)); }
ok() { echo "OK: $1"; }

if [[ -f "$SOLAR_HOME/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SOLAR_HOME/.env"
  set +a
fi

if [[ -f "$SOLAR_CORE_ROOT/scripts/sun-workspace-doctor.sh" ]]; then
  bash "$SOLAR_CORE_ROOT/scripts/sun-workspace-doctor.sh" "$@" || err_count=$((err_count + 1))
else
  err "sun-workspace-doctor.sh not found under SOLAR_CORE_ROOT"
fi

for f in CLAUDE.md GEMINI.md .cursorrules; do
  if [[ -L "$SOLAR_HOME/$f" ]]; then
    ok "$f -> $(readlink "$SOLAR_HOME/$f")"
  elif [[ -f "$SOLAR_HOME/$f" ]] && grep -q "symlink unavailable" "$SOLAR_HOME/$f" 2>/dev/null; then
    warn "$f is a stub (symlink failed; OneDrive/Windows?)"
  elif [[ -f "$SOLAR_HOME/$f" ]]; then
    warn "$f is a regular file, not a symlink to AGENTS.md"
  fi
done

if command -v git >/dev/null 2>&1 && git -C "$SOLAR_HOME" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git -C "$SOLAR_HOME" ls-files --error-unmatch .env >/dev/null 2>&1; then
    warn ".env is tracked by git in SOLAR_HOME (secrets risk)"
  else
    ok ".env not tracked by git"
  fi
fi

SOLAR_CLIENT_SCRIPT_DIR="$SCRIPT_DIR"
# shellcheck source=client_doctor_lib.sh
source "$SCRIPT_DIR/client_doctor_lib.sh"

_port_check_verbose() {
  local var="$1"
  local port="${!var:-}"
  [[ -n "$port" ]] || return 0

  local pid
  pid="$(_solar_client_port_listener_pid "$port" || true)"
  [[ -n "$pid" ]] || return 0

  case "$var" in
    SOLAR_INTERFACE_PORT)
      if _solar_client_is_interface_port "$port" "$pid"; then
        ok "$var=$port in use by solar-interface (pid $pid)"
        return 0
      fi
      ;;
    SOLAR_HTTP_PORT)
      if _solar_client_is_http_port "$port" "$pid"; then
        ok "$var=$port in use by solar-transport-gateway (pid $pid)"
        return 0
      fi
      ;;
  esac

  warn "$var=$port is in use by a non-Solar process (pid $pid); override in .env if another workspace"
}

_port_check_verbose SOLAR_INTERFACE_PORT
_port_check_verbose SOLAR_HTTP_PORT

if [[ -d "$SOLAR_HOME/.solar" && ! -f "$SOLAR_HOME/.solar/manifest.json" ]]; then
  warn ".solar/ exists but manifest.json is missing"
fi

echo "Summary: $err_count error(s), $warn_count warning(s)"
[[ "$err_count" -eq 0 ]]
