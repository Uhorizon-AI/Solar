#!/usr/bin/env bash
# Native Codex agents through the real entrypoints: sync-clients.sh and
# client_sync.sh. Temp workspace and synthetic planets only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-client/scripts"
SYNC_CLIENTS="$SCRIPTS/sync-clients.sh"
CLIENT_SYNC="$SCRIPTS/client_sync.sh"
SOLAR_INSTALL="$(cd "$CORE_ROOT/.." && pwd)"

# shellcheck source=../../support/shell_runtime_guard.sh
source "$CORE_ROOT/tests/support/shell_runtime_guard.sh"
# shellcheck source=/dev/null
source "$SCRIPTS/client_lib.sh"

PASS=0
FAIL=0
ok() { echo "PASS: $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
assert_ok() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi; }
assert_fails() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label"; else ok "$label"; fi; }
assert_eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (got='$2' want='$3')"; fi; }
assert_missing() { if [[ -e "$2" || -L "$2" ]]; then bad "$1 (present: $2)"; else ok "$1"; fi; }

TMP="$(mktemp -d)"
trap 'chmod -R u+rwx "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT

mkdir -p "$TMP/guard-bin" "$TMP/guard-runtime"
cat >"$TMP/guard-bin/launchctl" <<'EOS'
#!/usr/bin/env bash
exit 1
EOS
chmod +x "$TMP/guard-bin/launchctl"
export PATH="$TMP/guard-bin:${PATH}"
unset SOLAR_APP_DATA
export SOLAR_RUNTIME_ROOT="$TMP/guard-runtime"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl"
export CODEX_HOME="$TMP/external-codex-home"
mkdir -p "$CODEX_HOME"
echo '# external' >"$CODEX_HOME/config.toml"
solar_test_guard

WS="$TMP/workspace"
mkdir -p "$WS/sun" "$WS/.solar" "$WS/planets/demo/agents" "$WS/planets/personal-x/agents"
cat >"$WS/.solar/settings.json" <<'EOS'
{
  "layout": "solar-client-v1.2",
  "scope": "workspace",
  "core_source": "global",
  "custom_user": "keep-me"
}
EOS
agent() { # planet name
  printf -- '---\nname: %s\ndescription: Synthetic %s role.\n---\n\n# %s\n\nBody.\n' "$2" "$2" "$2" >"$WS/planets/$1/agents/$2.md"
}
agent demo sales
agent demo support
agent personal-x diary

export SOLAR_WORKSPACE="$WS"
export SOLAR_ROOT="$SOLAR_INSTALL"
cd "$WS"

tree_state() {
  python3 - "$1" <<'PY'
import os, sys, hashlib
out = []
for d, dirs, files in os.walk(sys.argv[1]):
    st = os.lstat(d)
    out.append((d, st.st_mtime_ns))
    for f in sorted(files):
        p = os.path.join(d, f)
        out.append((p, os.lstat(p).st_mtime_ns, hashlib.sha256(open(p, "rb").read()).hexdigest()))
print(sorted(out))
PY
}
settings_key() { python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])).get(sys.argv[2])))' "$WS/.solar/settings.json" "$1"; }

# 1. Off by default: sync creates nothing under .codex/agents.
OUT="$(bash "$SYNC_CLIENTS" --codex-only 2>&1)"
assert_missing "default: no .codex/agents" "$WS/.codex/agents"
assert_ok "default: sync says disabled" grep -q 'disabled (opt-in)' <<<"$OUT"
assert_ok "default: skills still published" test -d "$WS/.agents"

# 2. --claude-only keeps the old behaviour and never creates .codex/agents.
bash "$SYNC_CLIENTS" --claude-only >/dev/null 2>&1
assert_ok "claude: agents are symlinked as before" test -L "$WS/.claude/agents/demo:sales.md"
assert_missing "claude-only: no .codex" "$WS/.codex"

# 3. Codex-specific exclusion leaves the global list alone.
bash "$CLIENT_SYNC" exclude add --client codex personal-x >/dev/null
assert_eq "codex list" "$(bash "$CLIENT_SYNC" exclude list --client codex)" "personal-x"
assert_eq "global list unchanged" "$(bash "$CLIENT_SYNC" exclude list)" "(none)"
assert_eq "settings: codex block" "$(settings_key codex_agents)" '{"enabled": false, "exclude_planets": ["personal-x"], "exclude_agents": []}'
assert_eq "settings: global key not created" "$(settings_key sync_exclude_planets)" "null"
assert_eq "settings: unrelated key kept" "$(settings_key custom_user)" '"keep-me"'
bash "$CLIENT_SYNC" exclude --client codex add demo:support >/dev/null
assert_ok "identity exclusion listed" grep -qx 'demo:support' <(bash "$CLIENT_SYNC" exclude list --client codex)
bash "$CLIENT_SYNC" exclude remove demo:support --client codex >/dev/null
assert_eq "identity exclusion removed" "$(bash "$CLIENT_SYNC" exclude list --client codex)" "personal-x"
assert_fails "unknown client is rejected" bash "$CLIENT_SYNC" exclude list --client nope
assert_fails "--client without value is rejected" bash "$CLIENT_SYNC" exclude list --client
RC=0; bash "$CLIENT_SYNC" exclude list --client nope >/dev/null 2>&1 || RC=$?
assert_eq "unknown client exits 2" "$RC" "2"

# 4. Scope preview shows the exclusion and opens nothing.
OUT="$(bash "$CLIENT_SYNC" codex-agents preview)"
assert_ok "preview: personal planet excluded" grep -q 'personal-x: excluded (codex)' <<<"$OUT"
assert_ok "preview: demo would be read" grep -q 'demo: would read' <<<"$OUT"
assert_missing "preview: wrote nothing" "$WS/.codex"
OUT="$(bash "$CLIENT_SYNC" codex-agents preview --contents)"
assert_ok "preview --contents lists adds" grep -q 'would add: solar__demo__sales.toml' <<<"$OUT"
assert_missing "preview --contents wrote nothing" "$WS/.codex"
assert_eq "status disabled" "$(bash "$CLIENT_SYNC" codex-agents status | head -1)" "Codex agents: disabled"
assert_fails "unknown codex-agents subcommand" bash "$CLIENT_SYNC" codex-agents nope

# 5. Enable and publish through sync.
bash "$CLIENT_SYNC" codex-agents enable >/dev/null
assert_eq "enabled flag" "$(settings_key codex_agents | python3 -c 'import json,sys; print(json.load(sys.stdin)["enabled"])')" "True"
bash "$SYNC_CLIENTS" --codex-only >/dev/null 2>&1
assert_ok "demo:sales published" test -f "$WS/.codex/agents/solar__demo__sales.toml"
assert_ok "demo:support published" test -f "$WS/.codex/agents/solar__demo__support.toml"
assert_missing "excluded planet not published" "$WS/.codex/agents/solar__personal_x__diary.toml"
assert_fails "personal planet absent from manifest" grep -q 'personal' "$WS/.codex/agents/.solar-managed.json"
assert_eq "external CODEX_HOME untouched" "$(cat "$CODEX_HOME/config.toml")" "# external"
assert_missing "no .codex/config.toml created" "$WS/.codex/config.toml"

# 6. Second run is a byte and mtime no-op; other clients leave .codex alone.
BEFORE="$(tree_state "$WS/.codex")"
sleep 1
bash "$SYNC_CLIENTS" --codex-only >/dev/null 2>&1
assert_eq "second sync changes nothing" "$(tree_state "$WS/.codex")" "$BEFORE"
bash "$SYNC_CLIENTS" --claude-only >/dev/null 2>&1
assert_eq "claude sync leaves .codex alone" "$(tree_state "$WS/.codex")" "$BEFORE"

# 7. Retire after removing a contract.
rm "$WS/planets/demo/agents/support.md"
bash "$SYNC_CLIENTS" --codex-only >/dev/null 2>&1
assert_missing "retired agent file removed" "$WS/.codex/agents/solar__demo__support.toml"
assert_ok "other agent remains" test -f "$WS/.codex/agents/solar__demo__sales.toml"

# 8. Conflict: sync warns, continues and exits 0; the unmanaged file is untouched.
agent demo extra
echo 'manual' >"$WS/.codex/agents/solar__demo__extra.toml"
agent demo fresh
RC=0
OUT="$(bash "$SYNC_CLIENTS" --codex-only 2>&1)" || RC=$?
assert_eq "conflict does not fail sync" "$RC" "0"
assert_ok "conflict is reported" grep -q 'left untouched because of conflicts' <<<"$OUT"
assert_eq "conflicting file untouched" "$(cat "$WS/.codex/agents/solar__demo__extra.toml")" "manual"
assert_ok "non-conflicting agent still published" test -f "$WS/.codex/agents/solar__demo__fresh.toml"
rm "$WS/.codex/agents/solar__demo__extra.toml" "$WS/planets/demo/agents/extra.md"

# 9. Hard failure: other clients still sync, overall exit is non-zero.
rm -rf "$WS/.claude"
mv "$WS/.codex" "$TMP/codex-real"
ln -s "$TMP/codex-real" "$WS/.codex"
RC=0
OUT="$(bash "$SYNC_CLIENTS" --codex-only --claude-only 2>&1)" || RC=$?
assert_ok "unsafe .codex makes sync exit non-zero" test "$RC" -ne 0
assert_ok "failure is reported" grep -q 'Codex agent publication failed' <<<"$OUT"
assert_ok "claude still synced after codex agent failure" test -L "$WS/.claude/agents/demo:sales.md"
rm "$WS/.codex"
mv "$TMP/codex-real" "$WS/.codex"

# 10. Global exclusion applies to Codex agents; plain exclude behaves as before.
bash "$CLIENT_SYNC" exclude add demo >/dev/null
assert_eq "plain exclude list" "$(bash "$CLIENT_SYNC" exclude list)" "demo"
assert_eq "codex list not changed by global" "$(bash "$CLIENT_SYNC" exclude list --client codex)" "personal-x"
bash "$SYNC_CLIENTS" --codex-only >/dev/null 2>&1
assert_missing "globally excluded planet retired for Codex" "$WS/.codex/agents/solar__demo__sales.toml"
bash "$CLIENT_SYNC" exclude remove demo >/dev/null
assert_eq "plain exclude list empty again" "$(bash "$CLIENT_SYNC" exclude list)" "(none)"
bash "$SYNC_CLIENTS" --codex-only >/dev/null 2>&1
assert_ok "agents come back once the global exclusion is lifted" test -f "$WS/.codex/agents/solar__demo__fresh.toml"
RC=0; bash "$CLIENT_SYNC" exclude add >/dev/null 2>&1 || RC=$?
assert_eq "plain exclude add without planet still exits 2" "$RC" "2"

# 11. Other settings writers keep the codex_agents block.
BLOCK_BEFORE="$(settings_key codex_agents)"
solar_client_write_settings_v12 "$WS" "$SOLAR_INSTALL"
assert_eq "write_settings_v12 keeps codex_agents" "$(settings_key codex_agents)" "$BLOCK_BEFORE"
solar_client_write_sync_exclude_planets "$WS" other
assert_eq "exclude writer keeps codex_agents" "$(settings_key codex_agents)" "$BLOCK_BEFORE"
solar_client_write_sync_exclude_skills "$WS" some:skill
assert_eq "skill exclude writer keeps codex_agents" "$(settings_key codex_agents)" "$BLOCK_BEFORE"
solar_client_touch_manifest_synced "$WS" >/dev/null 2>&1 || true
assert_eq "touch keeps codex_agents" "$(settings_key codex_agents)" "$BLOCK_BEFORE"
solar_client_repair_manifest "$WS" "$SOLAR_INSTALL" >/dev/null 2>&1 || true
assert_eq "repair keeps codex_agents" "$(settings_key codex_agents)" "$BLOCK_BEFORE"

# 12. disable stops publication but leaves files.
bash "$CLIENT_SYNC" codex-agents disable >/dev/null
bash "$SYNC_CLIENTS" --codex-only >/dev/null 2>&1
assert_ok "disable leaves published files" test -f "$WS/.codex/agents/solar__demo__fresh.toml"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
