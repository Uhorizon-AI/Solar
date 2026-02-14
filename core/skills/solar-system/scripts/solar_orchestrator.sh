#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage:
  bash core/skills/solar-system/scripts/solar_orchestrator.sh --once
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" != "--once" ]]; then
  usage >&2
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source ".env"
  set +a
fi

normalize_csv() {
  local raw="$1"
  echo "$raw" | awk -F',' '
    {
      for (i = 1; i <= NF; i++) {
        x = $i
        gsub(/^[ \t]+|[ \t]+$/, "", x)
        if (x == "") continue
        if (!(x in seen)) {
          seen[x] = 1
          if (out == "") out = x
          else out = out "," x
        }
      }
    }
    END { print out }
  '
}

has_feature() {
  local f="$1"
  [[ -n "${FEATURES:-}" ]] && echo ",$FEATURES," | grep -q ",$f,"
}

LOCK_DIR="${SOLAR_SYSTEM_LOCK_DIR:-/tmp/com.solar.system.lock}"
LOCK_PID_FILE="$LOCK_DIR/pid"

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" >"$LOCK_PID_FILE"
    return 0
  fi

  if [[ -f "$LOCK_PID_FILE" ]]; then
    local existing_pid
    existing_pid="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
      echo "⏸️  Skipping tick: orchestrator already running (pid=$existing_pid)."
      return 1
    fi
    rm -rf "$LOCK_DIR" 2>/dev/null || true
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      echo "$$" >"$LOCK_PID_FILE"
      return 0
    fi
  fi

  echo "⏸️  Skipping tick: could not acquire orchestrator lock."
  return 1
}

release_lock() {
  rm -rf "$LOCK_DIR" 2>/dev/null || true
}

if ! acquire_lock; then
  exit 0
fi
trap release_lock EXIT INT TERM

FEATURES="$(normalize_csv "${SOLAR_SYSTEM_FEATURES:-}")"
if [[ -z "$FEATURES" ]]; then
  echo "⏸️  No Solar system features enabled (SOLAR_SYSTEM_FEATURES is empty)."
  exit 0
fi

echo "Solar system tick started. Features: $FEATURES"

failures=0

if has_feature "async-tasks"; then
  echo "▶ Running feature: async-tasks"
  if ! bash core/skills/solar-async-tasks/scripts/run_worker.sh --once; then
    echo "❌ async-tasks feature failed." >&2
    failures=$((failures + 1))
  fi
fi

if has_feature "transport-gateway"; then
  echo "▶ Running feature: transport-gateway"
  if ! bash core/skills/solar-system/scripts/ensure_transport_gateway.sh; then
    echo "❌ transport-gateway feature failed." >&2
    failures=$((failures + 1))
  fi
fi

for token in $(echo "$FEATURES" | tr ',' ' '); do
  case "$token" in
    async-tasks|transport-gateway) ;;
    *) echo "⚠️  Unknown feature token ignored: $token" ;;
  esac
done

if [[ "$failures" -gt 0 ]]; then
  echo "❌ Solar system tick finished with $failures failure(s)." >&2
  exit 1
fi

echo "✅ Solar system tick completed."
