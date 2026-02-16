#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE=".env"
BLOCK_HEADER="# [solar-router] required environment"

if [[ ! -f "$ROOT_ENV_FILE" ]]; then
  touch "$ROOT_ENV_FILE"
  echo "Created $ROOT_ENV_FILE"
fi

read_key() {
  local key="$1"
  if grep -Eq "^${key}=" "$ROOT_ENV_FILE"; then
    grep -E "^${key}=" "$ROOT_ENV_FILE" | tail -n1 | cut -d= -f2-
    return 0
  fi
  return 1
}

# Default value for the only required variable
provider_priority="codex,claude,gemini"

# Read existing value (new name first, then migrate from old name)
if existing="$(read_key "SOLAR_ROUTER_PROVIDER_PRIORITY")"; then
  provider_priority="$existing"
elif existing="$(read_key "SOLAR_AI_PROVIDER_PRIORITY")"; then
  provider_priority="$existing"
  echo "Migrating SOLAR_AI_PROVIDER_PRIORITY → SOLAR_ROUTER_PROVIDER_PRIORITY"
fi

# Optional variables: only preserve if they exist (for migration)
optional_vars=()

# Runtime dir (optional, default in code: sun/runtime/router)
if existing="$(read_key "SOLAR_ROUTER_RUNTIME_DIR")"; then
  optional_vars+=("SOLAR_ROUTER_RUNTIME_DIR=${existing}")
elif existing="$(read_key "SOLAR_RUNTIME_DIR")"; then
  optional_vars+=("SOLAR_ROUTER_RUNTIME_DIR=${existing}")
  echo "Migrating SOLAR_RUNTIME_DIR → SOLAR_ROUTER_RUNTIME_DIR"
fi

# System prompt file (optional, default in code: core/skills/solar-router/assets/system_prompt.md)
if existing="$(read_key "SOLAR_ROUTER_SYSTEM_PROMPT_FILE")"; then
  optional_vars+=("SOLAR_ROUTER_SYSTEM_PROMPT_FILE=${existing}")
elif existing="$(read_key "SOLAR_SYSTEM_PROMPT_FILE")"; then
  optional_vars+=("SOLAR_ROUTER_SYSTEM_PROMPT_FILE=${existing}")
  echo "Migrating SOLAR_SYSTEM_PROMPT_FILE → SOLAR_ROUTER_SYSTEM_PROMPT_FILE"
fi

# Context turns (optional, default in code: 12)
if existing="$(read_key "SOLAR_ROUTER_CONTEXT_TURNS")"; then
  optional_vars+=("SOLAR_ROUTER_CONTEXT_TURNS=${existing}")
elif existing="$(read_key "SOLAR_CONTEXT_TURNS")"; then
  optional_vars+=("SOLAR_ROUTER_CONTEXT_TURNS=${existing}")
  echo "Migrating SOLAR_CONTEXT_TURNS → SOLAR_ROUTER_CONTEXT_TURNS"
fi

# Provider timeout (optional, default in code: 300)
if existing="$(read_key "SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC")"; then
  optional_vars+=("SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC=${existing}")
elif existing="$(read_key "SOLAR_AI_PROVIDER_TIMEOUT_SEC")"; then
  optional_vars+=("SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC=${existing}")
  echo "Migrating SOLAR_AI_PROVIDER_TIMEOUT_SEC → SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC"
fi

# Router timeout (optional, default in code: 310)
if existing="$(read_key "SOLAR_ROUTER_TIMEOUT_SEC")"; then
  optional_vars+=("SOLAR_ROUTER_TIMEOUT_SEC=${existing}")
elif existing="$(read_key "SOLAR_AI_ROUTER_TIMEOUT_SEC")"; then
  optional_vars+=("SOLAR_ROUTER_TIMEOUT_SEC=${existing}")
  echo "Migrating SOLAR_AI_ROUTER_TIMEOUT_SEC → SOLAR_ROUTER_TIMEOUT_SEC"
fi

# Custom command overrides (optional)
if existing="$(read_key "SOLAR_ROUTER_CODEX_CMD")"; then
  optional_vars+=("SOLAR_ROUTER_CODEX_CMD=${existing}")
elif existing="$(read_key "SOLAR_AI_CODEX_CMD")"; then
  optional_vars+=("SOLAR_ROUTER_CODEX_CMD=${existing}")
  echo "Migrating SOLAR_AI_CODEX_CMD → SOLAR_ROUTER_CODEX_CMD"
fi

if existing="$(read_key "SOLAR_ROUTER_CLAUDE_CMD")"; then
  optional_vars+=("SOLAR_ROUTER_CLAUDE_CMD=${existing}")
elif existing="$(read_key "SOLAR_AI_CLAUDE_CMD")"; then
  optional_vars+=("SOLAR_ROUTER_CLAUDE_CMD=${existing}")
  echo "Migrating SOLAR_AI_CLAUDE_CMD → SOLAR_ROUTER_CLAUDE_CMD"
fi

if existing="$(read_key "SOLAR_ROUTER_GEMINI_CMD")"; then
  optional_vars+=("SOLAR_ROUTER_GEMINI_CMD=${existing}")
elif existing="$(read_key "SOLAR_AI_GEMINI_CMD")"; then
  optional_vars+=("SOLAR_ROUTER_GEMINI_CMD=${existing}")
  echo "Migrating SOLAR_AI_GEMINI_CMD → SOLAR_ROUTER_GEMINI_CMD"
fi

# Prepare tmp file with cleaned content (remove all old and new variants)
tmp="$(mktemp)"
awk '
  $0 ~ /^SOLAR_ROUTER_PROVIDER_PRIORITY=/ { next }
  $0 ~ /^SOLAR_AI_PROVIDER_PRIORITY=/ { next }
  $0 ~ /^SOLAR_AI_DEFAULT_PROVIDER=/ { next }
  $0 ~ /^SOLAR_AI_FALLBACK_ORDER=/ { next }
  $0 ~ /^SOLAR_AI_ALLOWED_PROVIDERS=/ { next }
  $0 ~ /^SOLAR_AI_PROVIDER_MODE=/ { next }
  $0 ~ /^SOLAR_ROUTER_RUNTIME_DIR=/ { next }
  $0 ~ /^SOLAR_RUNTIME_DIR=/ { next }
  $0 ~ /^SOLAR_ROUTER_SYSTEM_PROMPT_FILE=/ { next }
  $0 ~ /^SOLAR_SYSTEM_PROMPT_FILE=/ { next }
  $0 ~ /^SOLAR_ROUTER_CONTEXT_TURNS=/ { next }
  $0 ~ /^SOLAR_CONTEXT_TURNS=/ { next }
  $0 ~ /^SOLAR_ROUTER_PROVIDER_TIMEOUT_SEC=/ { next }
  $0 ~ /^SOLAR_AI_PROVIDER_TIMEOUT_SEC=/ { next }
  $0 ~ /^SOLAR_ROUTER_TIMEOUT_SEC=/ { next }
  $0 ~ /^SOLAR_AI_ROUTER_TIMEOUT_SEC=/ { next }
  $0 ~ /^SOLAR_ROUTER_CODEX_CMD=/ { next }
  $0 ~ /^SOLAR_AI_CODEX_CMD=/ { next }
  $0 ~ /^SOLAR_ROUTER_CLAUDE_CMD=/ { next }
  $0 ~ /^SOLAR_AI_CLAUDE_CMD=/ { next }
  $0 ~ /^SOLAR_ROUTER_GEMINI_CMD=/ { next }
  $0 ~ /^SOLAR_AI_GEMINI_CMD=/ { next }
  $0 ~ /^# \[solar-router\] required environment$/ { next }
  { print }
' "$ROOT_ENV_FILE" > "$tmp"

# Find insertion point (after solar-telegram or solar-transport-gateway if present, otherwise at end)
insert_line=""
if grep -Eq "^# \[solar-transport-gateway\] required environment$" "$tmp"; then
  insert_line="$(grep -En "^# \[solar-transport-gateway\] required environment$" "$tmp" | tail -n1 | cut -d: -f1)"
  insert_line=$((insert_line - 1))
elif grep -Eq "^# \[solar-telegram\] required environment$" "$tmp"; then
  insert_line="$(grep -En "^# \[solar-telegram\] required environment$" "$tmp" | tail -n1 | cut -d: -f1)"
  insert_line=$((insert_line - 1))
fi

# Insert block
if [[ -n "$insert_line" && "$insert_line" -gt 0 ]]; then
  sed -n "1,${insert_line}p" "$tmp" > "${tmp}.out"
  echo "" >> "${tmp}.out"
  echo "$BLOCK_HEADER" >> "${tmp}.out"
  echo "SOLAR_ROUTER_PROVIDER_PRIORITY=${provider_priority}" >> "${tmp}.out"

  # Add optional vars only if they were defined
  if [[ ${#optional_vars[@]} -gt 0 ]]; then
    for var in "${optional_vars[@]}"; do
      echo "$var" >> "${tmp}.out"
    done
  fi

  sed -n "$((insert_line + 1)),\$p" "$tmp" >> "${tmp}.out"
  mv "${tmp}.out" "$tmp"
else
  # Append at end
  echo "" >> "$tmp"
  echo "$BLOCK_HEADER" >> "$tmp"
  echo "SOLAR_ROUTER_PROVIDER_PRIORITY=${provider_priority}" >> "$tmp"

  # Add optional vars only if they were defined
  if [[ ${#optional_vars[@]} -gt 0 ]]; then
    for var in "${optional_vars[@]}"; do
      echo "$var" >> "$tmp"
    done
  fi
fi

mv "$tmp" "$ROOT_ENV_FILE"

echo ""
echo "✓ solar-router environment variables configured in $ROOT_ENV_FILE"
echo ""
echo "Required variable:"
echo "  SOLAR_ROUTER_PROVIDER_PRIORITY=${provider_priority}"
if [[ ${#optional_vars[@]} -gt 0 ]]; then
  echo ""
  echo "Optional variables (preserved from migration):"
  for var in "${optional_vars[@]}"; do
    echo "  $var"
  done
fi
echo ""
echo "All other variables use sensible defaults (see SKILL.md)."
echo "Run 'bash core/skills/solar-router/scripts/diagnose_router.sh' to validate providers."
