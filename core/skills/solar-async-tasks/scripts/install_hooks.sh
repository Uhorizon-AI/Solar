#!/bin/bash

# Install hook templates for a specific resource
# Usage: install_hooks.sh [--force] <resource-name>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/task_lib.sh"

# Parse flags
FORCE_OVERWRITE=false
if [[ "${1:-}" == "--force" || "${1:-}" == "-f" ]]; then
    FORCE_OVERWRITE=true
    shift
fi

RESOURCE_NAME="${1:-}"

if [[ -z "$RESOURCE_NAME" ]]; then
    echo "Usage: install_hooks.sh [--force] <resource-name>" >&2
    echo "" >&2
    echo "Examples:" >&2
    echo "  install_hooks.sh chrome-dev-tools" >&2
    echo "  install_hooks.sh postgres" >&2
    echo "  install_hooks.sh my-custom-resource" >&2
    echo "" >&2
    echo "This will copy hook templates from assets/ to:" >&2
    echo "  \$SOLAR_TASK_ROOT/hooks/$RESOURCE_NAME/" >&2
    exit 1
fi

ensure_dirs

HOOKS_DIR="$SOLAR_TASK_ROOT/hooks/$RESOURCE_NAME"
ASSETS_DIR="$SCRIPT_DIR/../assets"

# Check if hooks already exist
if [[ -d "$HOOKS_DIR" ]]; then
    if [[ "$FORCE_OVERWRITE" == "true" ]]; then
        # Force mode: proceed silently
        :
    elif [[ -t 0 ]]; then
        # Interactive TTY: prompt user
        echo "⚠️  Hooks already exist for resource: $RESOURCE_NAME"
        echo "   Location: $HOOKS_DIR"
        read -p "   Overwrite? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "❌ Installation cancelled"
            exit 0
        fi
    else
        # Non-interactive without --force: fail
        echo "❌ Hooks already exist for resource: $RESOURCE_NAME" >&2
        echo "   Location: $HOOKS_DIR" >&2
        echo "   Use --force to overwrite, or remove hooks manually first." >&2
        exit 1
    fi
fi

# Create hooks directory
mkdir -p "$HOOKS_DIR"

# Copy templates
echo "📋 Installing hook templates for: $RESOURCE_NAME"
echo "   Target: $HOOKS_DIR"
echo ""

# Calculate portable path to task_lib.sh (relative from SOLAR_TASK_ROOT)
# Assumes SOLAR_TASK_ROOT is sun/runtime/async-tasks (default structure)
# If repo is moved, hooks remain functional as long as structure is intact
TASK_LIB_RELATIVE_PATH="\$SOLAR_TASK_ROOT/../../../core/skills/solar-async-tasks/scripts/task_lib.sh"

for hook in pre_start post_complete on_error; do
    SOURCE="$ASSETS_DIR/hook-${hook}.template"
    TARGET="$HOOKS_DIR/${hook}.sh"

    if [[ ! -f "$SOURCE" ]]; then
        echo "⚠️  Template not found: hook-${hook}.template (skipping)"
        continue
    fi

    # Copy template and replace placeholders
    # Note: Using single quotes for sed delimiter to preserve $SOLAR_TASK_ROOT variable
    sed -e "s|REPLACE_WITH_RESOURCE_NAME|$RESOURCE_NAME|g" \
        -e "s|REPLACE_WITH_TASK_LIB_PATH|$TASK_LIB_RELATIVE_PATH|g" \
        "$SOURCE" > "$TARGET"
    chmod +x "$TARGET"

    echo "✅ Created: ${hook}.sh"
done

echo ""
echo "✅ Hook templates installed successfully!"
echo ""
echo "Next steps:"
echo "1. Edit the hooks to add your cleanup logic:"
echo "   - pre_start.sh: Resource acquisition/initialization"
echo "   - post_complete.sh: Normal cleanup (close connections, etc.)"
echo "   - on_error.sh: Emergency cleanup (force kill, etc.)"
echo ""
echo "2. Configure a task to use this resource:"
echo "   bash $SCRIPT_DIR/set_cleanup.sh <task_id> $RESOURCE_NAME"
echo ""
echo "Hook locations:"
ls -lh "$HOOKS_DIR"/*.sh
