#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$ROOT_DIR/sun/preferences"
mkdir -p "$ROOT_DIR/sun/memories"
mkdir -p "$ROOT_DIR/sun/daily-log"
mkdir -p "$ROOT_DIR/planets"
mkdir -p "$ROOT_DIR/core"

if [ ! -f "$ROOT_DIR/sun/preferences/profile.md" ]; then
  cat > "$ROOT_DIR/sun/preferences/profile.md" <<'EOF'
# User Profile

## Identity Handshake
- Your name:
- How you want me to call you:
- How you want to call this assistant:
- Preferred language:
- Preferred tone:

## Communication Preferences
- Response format:

## Working Preferences
- Deep work windows:
- Meeting constraints:
- Decision style:

## Priorities
1.
2.
3.
EOF
fi

if [ ! -f "$ROOT_DIR/sun/memories/baseline.md" ]; then
  cat > "$ROOT_DIR/sun/memories/baseline.md" <<'EOF'
# Baseline Memory

## Stable Context
- Role:
- Current companies/projects:
- Strategic priorities:

## Constraints
- Time:
- Energy:
- Non-negotiables:
EOF
fi

TODAY_FILE="$ROOT_DIR/sun/daily-log/$(date +%F).md"
if [ ! -f "$TODAY_FILE" ]; then
  cat > "$TODAY_FILE" <<'EOF'
# Daily Log

## Today
- Focus:
- Constraints:
- Key tasks:

## Notes
- 
EOF
fi

SYNC_SCRIPT="$ROOT_DIR/core/scripts/sync-clients.sh"
if [ -x "$SYNC_SCRIPT" ]; then
  echo "Running client sync..."
  if ! "$SYNC_SCRIPT"; then
    echo "Warning: client sync failed. You can retry manually:"
    echo "  bash core/scripts/sync-clients.sh"
  fi
fi

RUN_DOCTOR="${SOLAR_RUN_WORKSPACE_DOCTOR:-0}"
CHECK_GIT="${SOLAR_DOCTOR_CHECK_GIT:-0}"

if [ "$RUN_DOCTOR" = "1" ]; then
  doctor_args=()
  if [ "$CHECK_GIT" = "1" ]; then
    doctor_args+=(--check-git)
  fi

  SUN_DOCTOR_SCRIPT="$ROOT_DIR/core/scripts/sun-workspace-doctor.sh"
  if [ -x "$SUN_DOCTOR_SCRIPT" ]; then
    echo "Running sun workspace doctor..."
    if ! "$SUN_DOCTOR_SCRIPT" "${doctor_args[@]}"; then
      echo "Warning: sun workspace doctor detected issues."
    fi
  fi

  PLANETS_DOCTOR_SCRIPT="$ROOT_DIR/core/scripts/planets-workspace-doctor.sh"
  if [ -x "$PLANETS_DOCTOR_SCRIPT" ]; then
    echo "Running planets workspace doctor..."
    if ! "$PLANETS_DOCTOR_SCRIPT" "${doctor_args[@]}"; then
      echo "Warning: planets workspace doctor detected issues."
    fi
  fi
else
  echo "Workspace doctor checks are on-demand."
  echo "Run manually when needed:"
  echo "  bash core/scripts/sun-workspace-doctor.sh"
  echo "  bash core/scripts/planets-workspace-doctor.sh"
  echo "Optional git checks:"
  echo "  bash core/scripts/sun-workspace-doctor.sh --check-git"
  echo "  bash core/scripts/planets-workspace-doctor.sh --check-git"
fi

echo "Solar bootstrap complete."
echo "Next steps:"
echo "1) Create a planet: mkdir -p planets/<planet-name>"
echo "2) Copy templates into the new planet"
echo "   cp core/templates/planet-AGENTS.md planets/<planet-name>/AGENTS.md"
echo "   cp core/templates/planet-memory.md planets/<planet-name>/memory.md"
