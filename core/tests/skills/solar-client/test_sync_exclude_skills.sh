#!/usr/bin/env bash
# A skill can be kept out of every client, core included.
#
# Two independent ways, one index: the skill's own `sync: false` frontmatter, and
# `sync_exclude_skills` in .solar/settings.json. `sync_exclude_planets` reaches
# neither — core is not a planet — which is why `solar-telegram` survived every
# earlier attempt to unpublish it.
#
# Everything here runs against a temporary workspace. The live client folders of
# this machine are never touched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../../../skills/solar-client/scripts" && pwd)"
SYNC_SCRIPT="$SCRIPTS_DIR/sync-clients.sh"
SOLAR_INSTALL="$(cd "$SCRIPTS_DIR/../../../.." && pwd)"
# shellcheck source=../../../skills/solar-client/scripts/client_lib.sh
source "$SCRIPTS_DIR/client_lib.sh"

PASS=0
FAIL=0

assert_present() {
  local label="$1" path="$2"
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "PASS: $label"; PASS=$((PASS + 1))
  else
    echo "FAIL: $label (missing: $path)" >&2; FAIL=$((FAIL + 1))
  fi
}

assert_missing() {
  local label="$1" path="$2"
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "FAIL: $label (still present: $path)" >&2; FAIL=$((FAIL + 1))
  else
    echo "PASS: $label"; PASS=$((PASS + 1))
  fi
}

assert_eq() {
  local label="$1" got="$2" want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: $label"; PASS=$((PASS + 1))
  else
    echo "FAIL: $label (got='$got' want='$want')" >&2; FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WS="$TMP/workspace"
mkdir -p "$WS/sun" "$WS/.solar" \
  "$WS/planets/demo/skills/kept" "$WS/planets/demo/skills/dropped"
cat >"$WS/.solar/settings.json" <<'EOF'
{
  "layout": "solar-client-v1.2",
  "core_source": "global",
  "requires_global_client": true,
  "sync_exclude_planets": []
}
EOF
cat >"$WS/planets/demo/skills/kept/SKILL.md" <<'EOF'
---
name: kept
description: a planet skill that stays published
---
EOF
cat >"$WS/planets/demo/skills/dropped/SKILL.md" <<'EOF'
---
name: dropped
description: a planet skill excluded by the operator's list
---
EOF

run_sync() {
  (cd "$WS" && SOLAR_ROOT="$SOLAR_INSTALL" bash "$SYNC_SCRIPT" \
    --claude-only --codex-only --cursor-only --gemini-only >/dev/null)
}

# --- 1. the skill's own frontmatter, on a core skill ------------------------
# solar-telegram declares `sync: false`: its verb is the gated MCP tool now, so
# it must not reach any client catalog, with nothing written in settings.
run_sync
for client in claude codex cursor gemini; do
  assert_missing "core skill with sync:false stays out ($client)" \
    "$WS/.$client/skills/solar-telegram"
done
assert_present "a core skill without the flag is still published" \
  "$WS/.claude/skills/solar-client"
assert_present "one index, four clients: cursor gets the copy" \
  "$WS/.cursor/skills/solar-client"
assert_present "planet skill published" "$WS/.claude/skills/demo:kept"
assert_present "planet skill published (cursor copy)" "$WS/.cursor/skills/demo:kept"

# --- 2. the operator's list, on a planet skill ------------------------------
solar_client_write_sync_exclude_skills "$WS" "demo:dropped"
assert_eq "exclusion is readable back" \
  "$(solar_client_read_sync_exclude_skills "$WS")" "demo:dropped"
run_sync
assert_missing "excluded planet skill leaves the symlink clients" \
  "$WS/.claude/skills/demo:dropped"
assert_missing "excluded planet skill leaves the copy client" \
  "$WS/.cursor/skills/demo:dropped"
assert_present "its sibling is untouched" "$WS/.claude/skills/demo:kept"

# --- 3. it prunes what a previous sync published ---------------------------
# The exclusion has to remove an entry that is already there, not merely skip it.
solar_client_write_sync_exclude_skills "$WS" "demo:dropped" "demo:kept"
run_sync
assert_missing "an already published skill is pruned (symlink)" \
  "$WS/.claude/skills/demo:kept"
assert_missing "an already published skill is pruned (copy)" \
  "$WS/.cursor/skills/demo:kept"

# --- 4. removing the exclusion publishes it again --------------------------
solar_client_write_sync_exclude_skills "$WS" "demo:dropped"
run_sync
assert_present "removing the entry publishes it again" "$WS/.claude/skills/demo:kept"

# --- 5. the planet list cannot do this -------------------------------------
# The reason this mechanism exists: excluding the planet "solar" would not have
# removed a core skill, because core skills do not come from a planet.
solar_client_write_sync_exclude_planets "$WS" "solar"
run_sync
assert_present "excluding a planet leaves core skills published" \
  "$WS/.claude/skills/solar-client"

# --- 6. settings stay valid JSON with both lists ---------------------------
assert_eq "both lists coexist" \
  "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["sync_exclude_planets"], d["sync_exclude_skills"])' "$WS/.solar/settings.json")" \
  "['solar'] ['demo:dropped']"

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
