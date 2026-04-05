#!/usr/bin/env bash
# create-planet.sh
# Create a new Solar planet with proper structure
#
# Usage:
#   bash core/scripts/create-planet.sh <planet-name>
#   bash core/scripts/create-planet.sh --code-repo <planet-name>

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANETS_DIR="$ROOT_DIR/planets"
TEMPLATE_DIR="$ROOT_DIR/core/templates"

log_ok() {
  echo -e "${GREEN}✓${NC} $1"
}

log_error() {
  echo -e "${RED}✗${NC} $1"
}

log_info() {
  echo -e "${BLUE}ℹ${NC} $1"
}

CODE_REPO=false

if [ $# -eq 2 ] && [ "$1" = "--code-repo" ]; then
  CODE_REPO=true
  shift
fi

if [ $# -ne 1 ]; then
  echo "Usage: $0 [--code-repo] <planet-name>"
  echo ""
  echo "Example:"
  echo "  $0 my-project"
  echo "  $0 --code-repo my-app"
  exit 1
fi

PLANET_NAME="$1"
PLANET_DIR="$PLANETS_DIR/$PLANET_NAME"

# Validate planet name (basic validation)
if [[ ! "$PLANET_NAME" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  log_error "Invalid planet name. Use only letters, numbers, dots, hyphens, and underscores."
  exit 1
fi

# Check if planet already exists
if [ -d "$PLANET_DIR" ]; then
  log_error "Planet '$PLANET_NAME' already exists at $PLANET_DIR"
  exit 1
fi

log_info "Creating planet: $PLANET_NAME"
echo ""

# Create planet directory
mkdir -p "$PLANET_DIR"
log_ok "Created directory: planets/$PLANET_NAME/"

# Copy AGENTS.md template
if [ -f "$TEMPLATE_DIR/planet-AGENTS.md" ]; then
  cp "$TEMPLATE_DIR/planet-AGENTS.md" "$PLANET_DIR/AGENTS.md"
  log_ok "Created AGENTS.md from template"
else
  log_error "Template not found: $TEMPLATE_DIR/planet-AGENTS.md"
  exit 1
fi

if [ "$CODE_REPO" = true ]; then
  if [ -f "$TEMPLATE_DIR/planet-CONTRIBUTING.md" ]; then
    sed "s/<planet-name>/$PLANET_NAME/g" \
      "$TEMPLATE_DIR/planet-CONTRIBUTING.md" > "$PLANET_DIR/CONTRIBUTING.md"
    mkdir -p "$PLANET_DIR/docs/tasks"
    log_ok "Created CONTRIBUTING.md for code-repo adoption"
    log_ok "Created docs/tasks/ for task specs"
  else
    log_error "Template not found: $TEMPLATE_DIR/planet-CONTRIBUTING.md"
    exit 1
  fi
fi

# Create symlinks for AI client compatibility
cd "$PLANET_DIR"
ln -snf AGENTS.md CLAUDE.md
log_ok "Created CLAUDE.md -> AGENTS.md"

ln -snf AGENTS.md GEMINI.md
log_ok "Created GEMINI.md -> AGENTS.md"

cd "$ROOT_DIR"

echo ""
log_info "Planet '$PLANET_NAME' created successfully!"
echo ""
echo "Next steps:"
echo "  1. Edit planets/$PLANET_NAME/AGENTS.md to define scope and governance"
if [ "$CODE_REPO" = true ]; then
  echo "  2. Review planets/$PLANET_NAME/CONTRIBUTING.md and replace placeholder checks"
  echo "  3. Use docs/tasks/ for standard-or-higher solar-code task specs"
  NEXT_STEP=4
else
  NEXT_STEP=2
fi
echo "  $NEXT_STEP. (Optional) Create MEMORY.md for domain learnings when patterns emerge:"
echo "       cp core/templates/planet-MEMORY.md planets/$PLANET_NAME/MEMORY.md"
echo "  $((NEXT_STEP + 1)). (Optional) Create skills/agents/commands folders as needed:"
echo "       mkdir -p planets/$PLANET_NAME/skills/my-skill"
echo "       echo '# My Skill' > planets/$PLANET_NAME/skills/my-skill/SKILL.md"
echo "  $((NEXT_STEP + 2)). When adding resources: keep AGENTS.md in sync (Agents, Commands, Skills, Request Routing)"
echo "  $((NEXT_STEP + 3)). Sync to AI clients:"
echo "       bash core/scripts/sync-clients.sh"
echo ""
