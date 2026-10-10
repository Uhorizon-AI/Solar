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

# shellcheck source=../../support/shell_runtime_guard.sh
source "$SCRIPT_DIR/../../support/shell_runtime_guard.sh"
mkdir -p "$TMP/guard-bin" "$TMP/guard-runtime"
cat >"$TMP/guard-bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/guard-bin/launchctl"
export PATH="$TMP/guard-bin:${PATH}"
unset SOLAR_APP_DATA
export SOLAR_RUNTIME_ROOT="$TMP/guard-runtime"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl"
solar_test_guard

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
assert_missing "first sync does not link Codex under .codex/skills" "$WS/.codex/skills/gone:ghost"
assert_present "first sync copies the planet skill where Codex reads it" "$WS/.agents/skills/gone:ghost"
if [[ -L "$WS/.agents/skills/gone:ghost" ]]; then
  echo "FAIL: Codex copy is a symlink" >&2
  FAIL=$((FAIL + 1))
else
  echo "PASS: Codex copy is not a symlink"
  PASS=$((PASS + 1))
fi

# Remove planet source → IDE links become dangling.
rm -rf "$WS/planets/gone"

# Also plant a non-index leftover (real dir, not dangling) that must be pruned.
mkdir -p "$WS/.claude/skills/stale-manual/extra"
echo "leftover" >"$WS/.claude/skills/stale-manual/SKILL.md"
mkdir -p "$WS/.claude/agents"
ln -s "/nonexistent/agent.md" "$WS/.claude/agents/gone:dead-agent.md"
mkdir -p "$WS/.claude/commands"
ln -s "/nonexistent/cmd.md" "$WS/.claude/commands/gone:dead-cmd.md"

# A Solar symlink left under .codex/skills from an older sync.
mkdir -p "$WS/.codex/skills"
ln -s "$WS/planets/gone/skills/ghost" "$WS/.codex/skills/gone:ghost"

(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --claude-only --codex-only >/dev/null
)

assert_missing "prunes dangling planet skill (claude)" "$WS/.claude/skills/gone:ghost"
assert_missing "prunes dangling Solar symlink under .codex/skills" "$WS/.codex/skills/gone:ghost"
assert_missing "prunes the Codex copy when the planet leaves the index" "$WS/.agents/skills/gone:ghost"
assert_missing "prunes stale non-index skill dir" "$WS/.claude/skills/stale-manual"
assert_missing "prunes dangling agent symlink" "$WS/.claude/agents/gone:dead-agent.md"
assert_missing "prunes dangling command symlink" "$WS/.claude/commands/gone:dead-cmd.md"

# Core skill from SOLAR_ROOT should still be linked after prune.
assert_present "keeps indexed core skill" "$WS/.claude/skills/solar-client"

# Simulate a resource rename, including real managed copies and unrelated data.
mkdir -p "$WS/planets/rename-fixture/skills/draft-tool" "$WS/.agents/skills/local-notes"
cat >"$WS/planets/rename-fixture/skills/draft-tool/SKILL.md" <<'EOF'
---
name: draft-tool
description: synthetic resource used to test renaming
---
EOF
printf '%s\n' 'user-owned content' >"$WS/.agents/skills/local-notes/notes.txt"
cp "$WS/.agents/skills/local-notes/notes.txt" "$TMP/expected-notes.txt"
(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --claude-only --cursor-only --codex-only >/dev/null
)
for surface in .claude .cursor .agents; do
  assert_present "publishes original resource ($surface)" "$WS/$surface/skills/rename-fixture:draft-tool"
done
mv "$WS/planets/rename-fixture/skills/draft-tool" "$WS/planets/rename-fixture/skills/final-tool"
sed 's/name: draft-tool/name: final-tool/' \
  "$WS/planets/rename-fixture/skills/final-tool/SKILL.md" >"$TMP/renamed-skill.md"
mv "$TMP/renamed-skill.md" "$WS/planets/rename-fixture/skills/final-tool/SKILL.md"
(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --claude-only --cursor-only --codex-only >/dev/null
)
for surface in .claude .cursor .agents; do
  assert_missing "removes original resource after rename ($surface)" "$WS/$surface/skills/rename-fixture:draft-tool"
  assert_present "publishes renamed resource ($surface)" "$WS/$surface/skills/rename-fixture:final-tool"
  assert_ok "renamed content matches source ($surface)" cmp \
    "$WS/planets/rename-fixture/skills/final-tool/SKILL.md" \
    "$WS/$surface/skills/rename-fixture:final-tool/SKILL.md"
done
assert_ok "preserves unrelated shared resource bytes" cmp \
  "$TMP/expected-notes.txt" "$WS/.agents/skills/local-notes/notes.txt"
assert_ok "records renamed resource ownership" grep -Fxq \
  'rename-fixture:final-tool' "$WS/.agents/skills/.solar-managed"
if grep -Fxq 'rename-fixture:draft-tool' "$WS/.agents/skills/.solar-managed"; then
  echo "FAIL: obsolete ownership survives rename" >&2
  FAIL=$((FAIL + 1))
else
  echo "PASS: obsolete ownership removed after rename"
  PASS=$((PASS + 1))
fi

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
