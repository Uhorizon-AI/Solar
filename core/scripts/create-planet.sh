#!/usr/bin/env bash
# create-planet.sh
# Create a new Solar planet with proper structure
#
# Usage:
#   bash core/scripts/create-planet.sh <planet-name>

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

if [ $# -ne 1 ]; then
  echo "Usage: $0 <planet-name>"
  echo ""
  echo "Example:"
  echo "  $0 my-project"
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
echo "  2. (Optional) Create MEMORY.md for domain learnings when patterns emerge:"
echo "       cp core/templates/planet-MEMORY.md planets/$PLANET_NAME/MEMORY.md"
echo "  3. (Optional) Create skills/agents/commands folders as needed:"
echo "       mkdir -p planets/$PLANET_NAME/skills/my-skill"
echo "       echo '# My Skill' > planets/$PLANET_NAME/skills/my-skill/SKILL.md"
echo "  4. When adding resources: keep AGENTS.md in sync (Agents, Commands, Skills, Request Routing)"
echo "  5. Sync to AI clients:"
echo "       bash core/scripts/sync-clients.sh"
echo ""
