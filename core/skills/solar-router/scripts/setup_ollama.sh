#!/usr/bin/env bash
# setup_ollama.sh
# Builds the local Ollama model `solar` used by solar-router.
# Usage: bash core/skills/solar-router/scripts/setup_ollama.sh [base-model]
# Example: bash core/skills/solar-router/scripts/setup_ollama.sh qwen3.5

SOLAR_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
BASE_MODEL="${1:-qwen3.5}"
MODEL_NAME="solar"

SYSTEM_PROMPT="$SOLAR_ROOT/core/skills/solar-router/assets/ollama_prompt.md"

if [[ ! -f "$SYSTEM_PROMPT" ]]; then
  echo "Error: $SYSTEM_PROMPT not found" >&2
  exit 1
fi

MODELFILE=$(mktemp /tmp/SolarModelfile.XXXXXX)

cat > "$MODELFILE" << MODELEOF
FROM $BASE_MODEL
SYSTEM """
$(cat "$SYSTEM_PROMPT")
"""
MODELEOF

echo "Building model '$MODEL_NAME' from '$BASE_MODEL'..."
ollama create "$MODEL_NAME" -f "$MODELFILE"
rm -f "$MODELFILE"

echo ""
echo "Done."
echo "The solar-router Ollama provider now targets:"
echo "  ollama run $MODEL_NAME --hidethinking --nowordwrap"
