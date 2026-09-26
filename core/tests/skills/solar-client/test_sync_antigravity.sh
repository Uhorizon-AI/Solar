#!/usr/bin/env bash
# Antigravity receives skill copies under .agents/skills, not symlinks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SYNC_SCRIPT="$CORE_ROOT/skills/solar-client/scripts/sync-clients.sh"
SOLAR_INSTALL="$(cd "$CORE_ROOT/.." && pwd)"

# shellcheck source=../../support/shell_runtime_guard.sh
source "$CORE_ROOT/tests/support/shell_runtime_guard.sh"

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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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
mkdir -p "$WS/sun" "$WS/.solar" \
  "$WS/planets/alpha/skills/commit-a" \
  "$WS/planets/beta/skills/commit-b" \
  "$WS/planets/demo/skills/hidden" \
  "$WS/planets/demo/skills/gone"
cat >"$WS/.solar/settings.json" <<'EOF'
{
  "layout": "solar-client-v1.2",
  "scope": "workspace",
  "core_source": "global",
  "sync_exclude_skills": ["demo:hidden"]
}
EOF
cat >"$WS/planets/alpha/skills/commit-a/SKILL.md" <<'EOF'
---
name: commit
description: alpha commit skill
---
EOF
cat >"$WS/planets/beta/skills/commit-b/SKILL.md" <<'EOF'
---
name: "commit"
description: beta commit skill
---
EOF
cat >"$WS/planets/demo/skills/hidden/SKILL.md" <<'EOF'
---
name: hidden
description: excluded from every client
---
EOF
cat >"$WS/planets/demo/skills/gone/SKILL.md" <<'EOF'
---
name: gone
description: published once, then removed from the index
---
EOF
mkdir -p "$WS/.agents/skills/mine" "$WS/.agents/skills/solar-client"
echo '---
name: mine
description: a skill the user keeps beside Solar
---' >"$WS/.agents/skills/mine/SKILL.md"
echo 'user-owned' >"$WS/.agents/skills/solar-client/KEEP"

out="$(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --antigravity-only
)"

skill_md="$WS/.agents/skills/solar-paths/SKILL.md"
runtime_py="$WS/.agents/skills/solar-paths/scripts/solar_runtime.py"

assert_ok "SKILL.md is a regular file" test -f "$skill_md"
assert_ok "SKILL.md is not a symlink" test ! -L "$skill_md"
assert_ok "skill directory is not a symlink" test ! -L "$WS/.agents/skills/solar-paths"
assert_ok "copied solar_runtime.py runs from .agents/skills" \
  python3 "$runtime_py" runtime
assert_missing "excluded skill is not published" "$WS/.agents/skills/demo:hidden"
assert_ok "a manual skill survives the sync" test -f "$WS/.agents/skills/mine/SKILL.md"
assert_ok "a user folder named like a Solar skill is left in place" \
  grep -qx 'user-owned' "$WS/.agents/skills/solar-client/KEEP"
assert_ok "that folder is not recorded" \
  bash -c '! grep -Fxq "solar-client" "$1"' _ "$WS/.agents/skills/.solar-managed"
assert_ok "the name collision is reported" grep -q "already has 'solar-client'" <<<"$out"
assert_ok "the published skill is present before it leaves the index" \
  test -f "$WS/.agents/skills/demo:gone/SKILL.md"
assert_ok "the ledger records the published skill" \
  grep -Fxq "demo:gone" "$WS/.agents/skills/.solar-managed"
assert_ok "the ledger does not record the manual skill" \
  bash -c '! grep -Fxq "mine" "$1"' _ "$WS/.agents/skills/.solar-managed"
assert_missing "commands are not published" "$WS/.agents/commands"
assert_missing "workflows are not published" "$WS/.agents/workflows"

rm -rf "$WS/planets/demo/skills/gone"
(
  cd "$WS"
  SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" --antigravity-only >/dev/null
)
assert_missing "a published skill that leaves the index is pruned" \
  "$WS/.agents/skills/demo:gone"
assert_ok "the manual skill is still there after the prune" \
  test -f "$WS/.agents/skills/mine/SKILL.md"
assert_ok "the user folder is still not overwritten after a second sync" \
  grep -qx 'user-owned' "$WS/.agents/skills/solar-client/KEEP"
assert_ok "shared frontmatter name is reported" grep -q "frontmatter name 'commit'" <<<"$out"
assert_ok "alpha directory name is unchanged" test -d "$WS/.agents/skills/alpha:commit-a"
assert_ok "beta directory name is unchanged" test -d "$WS/.agents/skills/beta:commit-b"
assert_ok "warning names both planets" grep -q "alpha:commit-a" <<<"$out"
assert_ok "warning names the other planet" grep -q "beta:commit-b" <<<"$out"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
