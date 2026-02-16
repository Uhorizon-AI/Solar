#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$ROOT_DIR/sun/preferences"
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

if [ ! -f "$ROOT_DIR/sun/MEMORY.md" ]; then
  cat > "$ROOT_DIR/sun/MEMORY.md" <<'EOF'
# Sun Memory

**Max: 200 lines. Free-form. Only operational learnings.**

---

## Patterns Discovered
- (Recurring patterns confirmed across work)

## Common Pitfalls
- (Mistakes and their solutions)

## Decisions
- (Architectural decisions during work, with date)

---

**Note:** For detailed notes, create topic files (e.g., `debugging.md`, `solar-patterns.md`) and link from here.
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
echo "1) Create a planet: bash core/scripts/create-planet.sh <planet-name>"
echo "2) Edit planets/<planet-name>/AGENTS.md to define scope and governance"
echo "3) (Optional) Add planet resources (skills/agents/commands), keep AGENTS.md in sync, then:"
echo "   bash core/scripts/sync-clients.sh"
