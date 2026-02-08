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

SETUP_MARKER="$ROOT_DIR/sun/.setup-complete"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$SETUP_MARKER"

SYNC_SCRIPT="$ROOT_DIR/core/scripts/sync-clients.sh"
if [ -x "$SYNC_SCRIPT" ]; then
  echo "Running client sync..."
  if ! "$SYNC_SCRIPT"; then
    echo "Warning: client sync failed. You can retry manually:"
    echo "  bash core/scripts/sync-clients.sh"
  fi
fi

echo "Solar bootstrap complete."
echo "Next steps:"
echo "1) Create a planet: mkdir -p planets/<planet-name>"
echo "2) Copy templates into the new planet"
echo "   cp core/templates/planet-AGENTS.md planets/<planet-name>/AGENTS.md"
echo "   cp core/templates/planet-memory.md planets/<planet-name>/memory.md"
