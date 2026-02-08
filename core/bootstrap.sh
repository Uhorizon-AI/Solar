#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$ROOT_DIR/sun/preferences"
mkdir -p "$ROOT_DIR/sun/memories"
mkdir -p "$ROOT_DIR/sun/daily-log"
mkdir -p "$ROOT_DIR/planets"
mkdir -p "$ROOT_DIR/planets/_template"
mkdir -p "$ROOT_DIR/core"

touch "$ROOT_DIR/sun/preferences/.gitkeep"
touch "$ROOT_DIR/sun/memories/.gitkeep"
touch "$ROOT_DIR/sun/daily-log/.gitkeep"

if [ ! -f "$ROOT_DIR/sun/preferences/profile.md" ]; then
  cat > "$ROOT_DIR/sun/preferences/profile.md" <<'EOF'
# User Profile

## Communication
- Tone:
- Language:
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

if [ ! -f "$ROOT_DIR/planets/_template/AGENTS.md" ]; then
  cat > "$ROOT_DIR/planets/_template/AGENTS.md" <<'EOF'
# Planet Guidelines

## Scope
- Domain:
- In scope:
- Out of scope:

## Governance
- Required checks:
- Security/data rules:
- Operational limits:

## Input Contract (Sun -> Planet)
- Objective:
- Constraints:
- Context:

## Output Contract (Planet -> Sun)
- Status:
- Deliverables:
- Risks:
- Next steps:
EOF
fi

if [ ! -f "$ROOT_DIR/planets/_template/memory.md" ]; then
  cat > "$ROOT_DIR/planets/_template/memory.md" <<'EOF'
# Planet Memory

## Facts
- 

## Decisions
- 

## Open Threads
- 
EOF
fi

echo "Solar bootstrap complete."
echo "Next steps:"
echo "1) Initialize git: git init"
echo "2) Create a planet: mkdir -p planets/<planet-name>"
echo "3) Copy templates into the new planet"
