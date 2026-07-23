#!/usr/bin/env bash
# Regression: solar client sync must prune stale IDE entries, including dangling
# symlinks left after a planet/skill/agent/command disappears from sources.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="$(cd "$SCRIPT_DIR/../../../skills/solar-client/scripts" && pwd)/sync-clients.sh"
SOLAR_INSTALL="$(cd "$(dirname "$SYNC_SCRIPT")/../../../.." && pwd)"

PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_missing() {
  local label="$1"
  local path="$2"
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "FAIL: $label (still present: $path)" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $label"
    PASS=$((PASS + 1))
  fi
}

assert_present() {
  local label="$1"
  local path="$2"
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label (missing: $path)" >&2
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WS="$TMP/workspace"
mkdir -p "$WS/sun" "$WS/planets/gone/skills/ghost" "$WS/.solar"
cat >"$WS/.solar/manifest.json" <<'EOF'
{
  "version": 11,
  "core_source": "global",
  "requires_global_client": true
}
EOF
cat >"$WS/planets/gone/skills/ghost/SKILL.md" <<'EOF'
---
name: ghost
description: temporary planet skill for prune regression
---
EOF

# First sync: planet skill should appear under Claude + Codex.
(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --claude-only --codex-only >/dev/null
)

assert_present "first sync links planet skill (claude)" "$WS/.claude/skills/gone:ghost"
assert_present "first sync links planet skill (codex)" "$WS/.codex/skills/gone:ghost"

# Remove planet source → IDE links become dangling.
rm -rf "$WS/planets/gone"

# Also plant a non-index leftover (real dir, not dangling) that must be pruned.
mkdir -p "$WS/.claude/skills/stale-manual/extra"
echo "leftover" >"$WS/.claude/skills/stale-manual/SKILL.md"
mkdir -p "$WS/.claude/agents"
ln -s "/nonexistent/agent.md" "$WS/.claude/agents/gone:dead-agent.md"
mkdir -p "$WS/.claude/commands"
ln -s "/nonexistent/cmd.md" "$WS/.claude/commands/gone:dead-cmd.md"

(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --claude-only --codex-only >/dev/null
)

assert_missing "prunes dangling planet skill (claude)" "$WS/.claude/skills/gone:ghost"
assert_missing "prunes dangling planet skill (codex)" "$WS/.codex/skills/gone:ghost"
assert_missing "prunes stale non-index skill dir" "$WS/.claude/skills/stale-manual"
assert_missing "prunes dangling agent symlink" "$WS/.claude/agents/gone:dead-agent.md"
assert_missing "prunes dangling command symlink" "$WS/.claude/commands/gone:dead-cmd.md"

# Core skill from SOLAR_ROOT should still be linked after prune.
assert_present "keeps indexed core skill" "$WS/.claude/skills/solar-client"

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
