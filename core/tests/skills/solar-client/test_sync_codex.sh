#!/usr/bin/env bash
# Codex reads .agents/skills. Sync must not publish a second tree under .codex/skills.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SYNC_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/sync-clients.sh"
SOLAR_INSTALL="$(cd "$CORE_ROOT/.." && pwd)"

# shellcheck source=../../support/shell_runtime_guard.sh
source "$CORE_ROOT/tests/support/shell_runtime_guard.sh"

PASS=0
FAIL=0

assert_missing() {
  local label="$1" path="$2"
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "FAIL: $label (still present: $path)" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $label"
    PASS=$((PASS + 1))
  fi
}

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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/guard-bin" "$TMP/guard-runtime"
cat >"$TMP/guard-bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/guard-bin/launchctl"
export PATH="$TMP/guard-bin:${PATH}"
unset SOLAR_APP_DATA CODEX_HOME
export SOLAR_RUNTIME_ROOT="$TMP/guard-runtime"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl"
solar_test_guard

WS="$TMP/workspace"
mkdir -p "$WS/sun" "$WS/.solar" \
  "$WS/.codex" "$WS/.codex/skills" \
  "$WS/planets/demo/skills/kept"
echo 'kept' >"$WS/.codex/config.toml"
cat >"$WS/.solar/settings.json" <<'EOF'
{
  "layout": "solar-client-v1.2",
  "scope": "workspace",
  "core_source": "global"
}
EOF
cat >"$WS/planets/demo/skills/kept/SKILL.md" <<'EOF'
---
name: kept
description: planet skill Codex should read from .agents/skills
---
EOF
ln -s "$SOLAR_INSTALL/core/skills/solar-paths" "$WS/.codex/skills/solar-paths"
ln -s "$WS/planets/demo/skills/kept" "$WS/.codex/skills/demo:kept"
ln -s "$TMP/not-solar" "$WS/.codex/skills/foreign-link"
echo 'leave me' >"$WS/.codex/skills/foreign-file"

(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --codex-only >/dev/null
)

assert_missing "core symlink is removed from .codex/skills" "$WS/.codex/skills/solar-paths"
assert_missing "planet symlink is removed from .codex/skills" "$WS/.codex/skills/demo:kept"
assert_ok "a foreign symlink survives" test -L "$WS/.codex/skills/foreign-link"
assert_ok "a foreign file survives" test -f "$WS/.codex/skills/foreign-file"
assert_ok ".codex itself stays because it holds config.toml" test -f "$WS/.codex/config.toml"
assert_ok "Codex copy is a directory under .agents/skills" test -d "$WS/.agents/skills/solar-paths"
assert_ok "Codex copy is not a symlink" test ! -L "$WS/.agents/skills/solar-paths"
assert_ok "copied SKILL.md is a regular file" test -f "$WS/.agents/skills/solar-paths/SKILL.md"
assert_ok "planet skill is copied for Codex" test -f "$WS/.agents/skills/demo:kept/SKILL.md"
assert_missing "sync did not recreate the core symlink" "$WS/.codex/skills/solar-paths"

# Only Solar links: the skills directory goes away, .codex does not.
rm -f "$WS/.codex/skills/foreign-link" "$WS/.codex/skills/foreign-file"
ln -s "$SOLAR_INSTALL/core/skills/solar-client" "$WS/.codex/skills/solar-client"
(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --codex-only >/dev/null
)
assert_missing "an empty .codex/skills is removed" "$WS/.codex/skills"
assert_ok ".codex stays after its skills directory is removed" test -d "$WS/.codex"
assert_ok "Codex copy is still published" test -f "$WS/.agents/skills/solar-client/SKILL.md"

# CODEX_HOME pointing somewhere else is not a write or delete target.
OTHER="$TMP/other-codex"
mkdir -p "$OTHER/skills"
ln -s "$SOLAR_INSTALL/core/skills/solar-paths" "$OTHER/skills/solar-paths"
echo 'foreign home' >"$OTHER/skills/notes.txt"
(
  cd "$WS"
  CODEX_HOME="$OTHER" SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --codex-only >/dev/null
)
assert_ok "a CODEX_HOME elsewhere keeps its Solar symlink" test -L "$OTHER/skills/solar-paths"
assert_ok "a CODEX_HOME elsewhere keeps its file" test -f "$OTHER/skills/notes.txt"
assert_missing "workspace .codex/skills is not recreated for that CODEX_HOME" "$WS/.codex/skills/solar-paths"

# .codex itself is a symlink into an external directory. Do not walk it.
EXT="$TMP/external-codex"
mkdir -p "$EXT/skills"
ln -s "$SOLAR_INSTALL/core/skills/solar-paths" "$EXT/skills/solar-paths"
echo 'external' >"$EXT/skills/keep.txt"
echo 'outside' >"$EXT/outside.txt"
EXT_SOLAR_BEFORE="$(readlink "$EXT/skills/solar-paths")"
rm -rf "$WS/.codex"
ln -s "$EXT" "$WS/.codex"
EXT_LINK_BEFORE="$(readlink "$WS/.codex")"
LINK_OUT="$(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --codex-only 2>&1
)"
assert_ok ".codex symlink is reported and left in place" grep -q 'is a symlink; leaving it untouched' <<<"$LINK_OUT"
assert_ok ".codex symlink still points at the external directory" test "$(readlink "$WS/.codex")" = "$EXT_LINK_BEFORE"
assert_ok "external Solar symlink is unchanged" test "$(readlink "$EXT/skills/solar-paths")" = "$EXT_SOLAR_BEFORE"
assert_ok "external file inside skills is unchanged" grep -qx 'external' "$EXT/skills/keep.txt"
assert_ok "external file beside skills is unchanged" grep -qx 'outside' "$EXT/outside.txt"

# .codex is real; only .codex/skills is the external symlink.
rm "$WS/.codex"
mkdir -p "$WS/.codex"
ln -s "$EXT/skills" "$WS/.codex/skills"
SKILLS_LINK_BEFORE="$(readlink "$WS/.codex/skills")"
SKILLS_OUT="$(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --codex-only 2>&1
)"
assert_ok ".codex/skills symlink is reported and left in place" grep -q 'is a symlink; leaving it untouched' <<<"$SKILLS_OUT"
assert_ok ".codex/skills symlink still points outside" test "$(readlink "$WS/.codex/skills")" = "$SKILLS_LINK_BEFORE"
assert_ok "external Solar symlink still unchanged" test "$(readlink "$EXT/skills/solar-paths")" = "$EXT_SOLAR_BEFORE"
assert_ok "external file inside skills still unchanged" grep -qx 'external' "$EXT/skills/keep.txt"
assert_ok "external directory was not removed" test -d "$EXT/skills"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
