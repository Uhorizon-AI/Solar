#!/usr/bin/env bash
# check_orchestrator.sh — Solar orchestrator + feature health check.
# Reports supervisor state and per-feature health. Emits a single verdict.
# Run from repo root: bash core/skills/solar-system/scripts/check_orchestrator.sh
#
# Exit codes (aligned with check_transport_gateway.sh):
#   0 = HEALTHY
#   2 = PARTIAL  (supervisor OK, one or more features degraded)
#   1 = DOWN     (supervisor down or critical feature down)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Portable timeout: uses gtimeout (Homebrew coreutils) or timeout (GNU).
# If neither is available, uses a pure-bash fallback (subshell + background kill).
# Mirrors get_timeout_cmd() from solar-async-tasks/scripts/task_lib.sh.
FEATURE_TIMEOUT=15

run_with_timeout() {
  if command -v gtimeout &>/dev/null; then
    gtimeout "$FEATURE_TIMEOUT" "$@"
    return $?
  elif command -v timeout &>/dev/null; then
    timeout "$FEATURE_TIMEOUT" "$@"
    return $?
  fi
  # Pure-bash fallback: run in a new process group, kill the whole group after timeout.
  set -m  # enable job control to get a process group
  "$@" &
  local child_pid=$!
  (sleep "$FEATURE_TIMEOUT" && kill -- -"$child_pid" 2>/dev/null) &
  local killer_pid=$!
  wait "$child_pid" 2>/dev/null
  local exit_code=$?
  kill "$killer_pid" 2>/dev/null
  wait "$killer_pid" 2>/dev/null || true
  set +m
  return $exit_code
}

# Severity aggregation: DOWN > PARTIAL > HEALTHY
# $1 = current worst, $2 = new candidate
worst_severity() {
  local current="$1" candidate="$2"
  if [[ "$current" == "DOWN" || "$candidate" == "DOWN" ]]; then
    echo "DOWN"
  elif [[ "$current" == "PARTIAL" || "$candidate" == "PARTIAL" ]]; then
    echo "PARTIAL"
  else
    echo "HEALTHY"
  fi
}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LABEL="${SOLAR_SYSTEM_LAUNCHD_LABEL:-com.solar.system}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/${UID}"

IFS=',' read -ra RAW_FEATURES <<< "${SOLAR_SYSTEM_FEATURES:-}"
FEATURES=()
for f in "${RAW_FEATURES[@]}"; do
  f="${f// /}"                  # strip spaces
  f="$(echo "$f" | tr '[:upper:]' '[:lower:]')"  # lowercase
  [[ -n "$f" ]] && FEATURES+=("$f")
done

# ---------------------------------------------------------------------------
# Check 1: Supervisor (launchd)
# ---------------------------------------------------------------------------

echo "Solar orchestrator status:"
echo "  label:    $LABEL"
echo "  features: ${SOLAR_SYSTEM_FEATURES:-<none>}"
echo ""

verdict="HEALTHY"

echo "── Supervisor"
if [[ -f "$PLIST" ]]; then
  echo "  plist_present:    true"
else
  echo "  plist_present:    false"
  verdict="$(worst_severity "$verdict" "DOWN")"
fi

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "  launchctl_loaded: true"
else
  echo "  launchctl_loaded: false"
  verdict="$(worst_severity "$verdict" "DOWN")"
fi

# ---------------------------------------------------------------------------
# Check 2: transport-gateway feature
# ---------------------------------------------------------------------------

feature_active() {
  local target="$1"
  for f in "${FEATURES[@]}"; do
    [[ "$f" == "$target" ]] && return 0
  done
  return 1
}

if feature_active "transport-gateway"; then
  echo ""
  echo "── Feature: transport-gateway"
  gw_out=""
  gw_code=0
  set +e
  gw_out="$(run_with_timeout bash core/skills/solar-transport-gateway/scripts/check_transport_gateway.sh 2>&1)"
  gw_code=$?
  set -e

  case "$gw_code" in
    0)
      echo "  status: HEALTHY"
      ;;
    2)
      echo "  status: PARTIAL"
      echo "  detail: $gw_out"
      verdict="$(worst_severity "$verdict" "PARTIAL")"
      ;;
    *)
      echo "  status: DOWN"
      echo "  detail: $gw_out"
      verdict="$(worst_severity "$verdict" "DOWN")"
      ;;
  esac
fi

# ---------------------------------------------------------------------------
# Check 3: async-tasks feature
# ---------------------------------------------------------------------------

if feature_active "async-tasks"; then
  echo ""
  echo "── Feature: async-tasks"
  async_severity="HEALTHY"

  # 3a. task_lib.sh present and executable
  TASK_LIB="core/skills/solar-async-tasks/scripts/task_lib.sh"
  if [[ -x "$TASK_LIB" ]]; then
    echo "  task_lib:    present"
  else
    echo "  task_lib:    MISSING or not executable"
    async_severity="$(worst_severity "$async_severity" "DOWN")"
  fi

  # 3b. Queue directory exists (source task_lib.sh to resolve SOLAR_TASK_ROOT)
  # shellcheck source=/dev/null
  source "$TASK_LIB" 2>/dev/null || true
  DIR_QUEUED="${DIR_QUEUED:-${SOLAR_TASK_ROOT:-sun/runtime/async-tasks}/queued}"
  if [[ -d "$DIR_QUEUED" ]]; then
    echo "  queue_dir:   present ($DIR_QUEUED)"
  else
    echo "  queue_dir:   MISSING ($DIR_QUEUED)"
    async_severity="$(worst_severity "$async_severity" "DOWN")"
  fi

  # 3c. Orphan lock check in $DIR_LOCKS
  DIR_LOCKS="${DIR_LOCKS:-${SOLAR_TASK_ROOT:-sun/runtime/async-tasks}/.locks}"
  orphan_found=false
  if [[ -d "$DIR_LOCKS" ]]; then
    for lock_file in "$DIR_LOCKS"/*.lock; do
      [[ -e "$lock_file" ]] || continue
      lock_name="$(basename "$lock_file")"
      pid="$(cat "$lock_file" 2>/dev/null || true)"
      if [[ "$pid" =~ ^[0-9]+$ ]]; then
        if ! kill -0 "$pid" 2>/dev/null; then
          echo "  lock [$lock_name]: orphan (pid=$pid dead)"
          orphan_found=true
          async_severity="$(worst_severity "$async_severity" "PARTIAL")"
        else
          echo "  lock [$lock_name]: active (pid=$pid)"
        fi
      else
        echo "  lock [$lock_name]: non-numeric content, ignored"
      fi
    done
  fi

  echo "  status: $async_severity"
  verdict="$(worst_severity "$verdict" "$async_severity")"
fi

# ---------------------------------------------------------------------------
# Warn on unknown features
# ---------------------------------------------------------------------------

for f in "${FEATURES[@]}"; do
  case "$f" in
    async-tasks|transport-gateway) ;;
    *) echo ""
       echo "  ⚠️  Unknown feature token ignored: $f" ;;
  esac
done

# ---------------------------------------------------------------------------
# Final verdict + suggested actions
# ---------------------------------------------------------------------------

echo ""
echo "── Verdict: $verdict"

if [[ "$verdict" != "HEALTHY" ]]; then
  echo ""
  echo "── Suggested actions:"

  # Supervisor issues
  if [[ ! -f "$PLIST" ]] || ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "  • LaunchAgent not installed or not loaded:"
    echo "    bash core/skills/solar-system/scripts/install_launchagent_macos.sh"
  fi

  # transport-gateway issues
  if feature_active "transport-gateway" && [[ "$gw_code" != "0" ]]; then
    GW_LOG="${SOLAR_GATEWAY_RUN_DIR:-/tmp/solar-transport-gateway}/cloudflared.log"
    tunnel_error=""
    if [[ -f "$GW_LOG" ]]; then
      tunnel_error="$(tail -n 20 "$GW_LOG" 2>/dev/null | grep -i "ERR\|error" | tail -n 3 || true)"
    fi

    if [[ "$gw_code" == "2" ]]; then
      # PARTIAL: local OK, tunnel degraded — diagnose why
      if echo "$tunnel_error" | grep -qi "unknown error registering\|registering the connection"; then
        echo "  • Tunnel named rechazado por Cloudflare (token inválido o tunnel eliminado):"
        echo "    1. Verifica el estado en: https://one.dash.cloudflare.com → Networks → Tunnels"
        echo "    2. Si el tunnel está inactivo o eliminado, reconfigúralo:"
        echo "       bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh"
      elif echo "$tunnel_error" | grep -qi "token\|credential\|auth"; then
        echo "  • Error de autenticación del tunnel — regenera el token en Cloudflare dashboard:"
        echo "    1. https://one.dash.cloudflare.com → Networks → Tunnels → solar-ai.uhorizon.ai"
        echo "    2. Copia el nuevo token y actualiza CLOUDFLARED_TUNNEL_TOKEN en .env"
        echo "    3. bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh"
      elif echo "$tunnel_error" | grep -qi "control stream\|QUIC stream\|Application error 0x0"; then
        echo "  • Tunnel caído por error de protocolo QUIC/control stream (puede ser transitorio):"
        echo "    bash core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh"
        echo "  • Si persiste, reconfigura el tunnel named:"
        echo "    bash core/skills/solar-transport-gateway/scripts/configure_named_tunnel.sh"
      elif echo "$tunnel_error" | grep -qi "connection refused\|dial\|network"; then
        echo "  • Tunnel sin conectividad de red — verifica tu conexión a internet y reintenta:"
        echo "    bash core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh"
      else
        echo "  • Tunnel degradado — reinicia el tunnel:"
        echo "    bash core/skills/solar-transport-gateway/scripts/ensure_transport_gateway.sh"
        if [[ -n "$tunnel_error" ]]; then
          echo "  • Último error en cloudflared.log:"
          echo "$tunnel_error" | sed 's/^/    /'
        fi
      fi
    else
      echo "  • Transport gateway down — run full setup/recovery:"
      echo "    bash core/skills/solar-transport-gateway/scripts/setup_transport_gateway.sh"
    fi
  fi

  # async-tasks issues
  if feature_active "async-tasks"; then
    if [[ ! -x "$TASK_LIB" ]]; then
      echo "  • async-tasks not set up — initialize runtime directories:"
      echo "    bash core/skills/solar-async-tasks/scripts/setup_async_tasks.sh"
    fi
    if [[ ! -d "$DIR_QUEUED" ]]; then
      echo "  • Queue directory missing — initialize runtime directories:"
      echo "    bash core/skills/solar-async-tasks/scripts/setup_async_tasks.sh"
    fi
    if [[ "${orphan_found:-false}" == "true" ]]; then
      echo "  • Orphan lock(s) detected — remove stale locks manually:"
      echo "    rm $DIR_LOCKS/*.lock"
      echo "    (verify no active tasks before removing)"
    fi
  fi

  # Generic deep troubleshooting
  echo "  • For deep LaunchAgent diagnostics:"
  echo "    bash core/skills/solar-system/scripts/diagnose_launchagent.sh"
fi

case "$verdict" in
  HEALTHY) exit 0 ;;
  PARTIAL) exit 2 ;;
  DOWN)    exit 1 ;;
esac
