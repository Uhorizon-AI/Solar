#!/usr/bin/env bash
# test_sync_exclude.sh — sync exclude CLI + settings v1.2 migration bits
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
# shellcheck source=../../../../core/skills/solar-client/scripts/client_lib.sh
source "$ROOT/core/skills/solar-client/scripts/client_lib.sh"

PASS=0
FAIL=0
assert_ok() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}
assert_eq() {
  local name="$1" got="$2" want="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name (got='$got' want='$want')"
    FAIL=$((FAIL + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WS="$TMP/ws"
mkdir -p "$WS/sun" "$WS/planets/demo/skills/demo-skill" "$WS/.solar" "$WS/.cursor/skills"
cat >"$WS/planets/demo/skills/demo-skill/SKILL.md" <<'EOF'
---
name: demo-skill
---
demo
EOF

# Minimal install root pointing at framework under test
export SOLAR_WORKSPACE="$WS"
export SOLAR_ROOT="$ROOT"
export SOLAR_BIN_DIR="$TMP/bin"
mkdir -p "$SOLAR_BIN_DIR"

solar_client_write_settings_v12 "$WS" "$ROOT"
assert_ok "writes settings.json" test -f "$WS/.solar/settings.json"
assert_ok "removes legacy after write from empty" test ! -f "$WS/.solar/manifest.json"
layout="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json"))["layout"])')"
assert_eq "layout v1.2" "$layout" "solar-client-v1.2"
scope="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json")).get("scope",""))')"
assert_eq "scope workspace" "$scope" "workspace"

# Legacy migrate: both files → settings wins; write removes manifest
printf '%s\n' '{"layout":"solar-client-v1.1","core_version":"old","sync_exclude_planets":["keep-me"],"custom_user":"x"}' \
  >"$WS/.solar/manifest.json"
printf '%s\n' '{"layout":"solar-client-v1.2","core_version":"new","scope":"workspace","sync_exclude_planets":["from-settings"],"custom_user":"y"}' \
  >"$WS/.solar/settings.json"
path="$(solar_client_settings_path "$WS")"
assert_eq "dual-read prefers settings" "$path" "$WS/.solar/settings.json"
got="$(solar_client_read_sync_exclude_planets "$WS" | tr '\n' ',')"
assert_eq "read exclude from settings" "$got" "from-settings,"

# Atomic mid-fail: legacy must not be deleted if commit (replace) never happens
printf '%s\n' '{"layout":"solar-client-v1.1","core_version":"old","marker":"legacy-keep"}' \
  >"$WS/.solar/manifest.json"
cp "$WS/.solar/settings.json" "$TMP/settings-before.json"
if SOLAR_CLIENT_TEST_FAIL_BEFORE_REPLACE=1 solar_client_write_settings_v12 "$WS" "$ROOT" 2>/dev/null; then
  echo "FAIL: mid-fail write should exit non-zero"
  FAIL=$((FAIL + 1))
else
  echo "PASS: mid-fail write exits non-zero"
  PASS=$((PASS + 1))
fi
assert_ok "mid-fail keeps legacy manifest" test -f "$WS/.solar/manifest.json"
marker="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/manifest.json")).get("marker",""))')"
assert_eq "mid-fail legacy content intact" "$marker" "legacy-keep"
assert_ok "mid-fail settings unchanged" cmp -s "$WS/.solar/settings.json" "$TMP/settings-before.json"
assert_ok "mid-fail leaves no orphan .settings.*.json tmp" \
  bash -c '! ls "'"$WS"'/.solar/.settings."*.json >/dev/null 2>&1'

solar_client_write_settings_v12 "$WS" "$ROOT" preserve_synced=1
assert_ok "after rewrite settings exists" test -f "$WS/.solar/settings.json"
assert_ok "after rewrite legacy removed" test ! -f "$WS/.solar/manifest.json"
excl="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json")).get("sync_exclude_planets"))')"
assert_eq "preserve sync_exclude_planets" "$excl" "['from-settings']"
custom="$(python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json")).get("custom_user",""))')"
assert_eq "preserve unknown key" "$custom" "y"

# CLI exclude via client_sync.sh (cd into WS to avoid SOLAR_WORKSPACE conflict with discovery)
SYNC="$ROOT/core/skills/solar-client/scripts/client_sync.sh"
(
  cd "$WS"
  export SOLAR_WORKSPACE="$WS"
  export SOLAR_ROOT="$ROOT"
  bash "$ROOT/core/skills/solar-client/scripts/sync-clients.sh" --cursor-only >/dev/null
  if [[ -e "$WS/.cursor/skills/demo:demo-skill" ]]; then
    echo synced >"$TMP/pre-exclude.txt"
  else
    echo missing >"$TMP/pre-exclude.txt"
  fi
  bash "$SYNC" exclude add demo >/dev/null
  bash "$SYNC" exclude add other >/dev/null
  list="$(bash "$SYNC" exclude list | tr '\n' ',')"
  printf '%s\n' "$list" >"$TMP/list1.txt"
  bash "$SYNC" exclude remove other >/dev/null
  bash "$SYNC" exclude remove demo >/dev/null
  bash "$SYNC" exclude remove from-settings >/dev/null
  bash "$SYNC" exclude list >"$TMP/list2.txt"
  python3 -c 'import json; print(json.load(open("'"$WS"'/.solar/settings.json"))["sync_exclude_planets"])' >"$TMP/empty.txt"
  bash "$SYNC" exclude add demo >/dev/null
  bash "$ROOT/core/skills/solar-client/scripts/sync-clients.sh" --cursor-only >/dev/null
  if bash "$SYNC" exclude add 2>"$TMP/err.txt"; then
    echo fail >"$TMP/add_missing.txt"
  else
    if grep -q "Unknown option" "$TMP/err.txt"; then
      echo leaked >"$TMP/add_missing.txt"
    else
      echo ok >"$TMP/add_missing.txt"
    fi
  fi
)
list="$(cat "$TMP/list1.txt")"
assert_eq "exclude list" "$list" "from-settings,demo,other,"

pre_exclude="$(cat "$TMP/pre-exclude.txt")"
assert_eq "planet skill exists before exclusion" "$pre_exclude" "synced"

empty="$(cat "$TMP/empty.txt")"
assert_eq "empty list is []" "$empty" "[]"
list2="$(cat "$TMP/list2.txt")"
assert_eq "list shows none" "$list2" "(none)"

if [[ -e "$WS/.cursor/skills/demo:demo-skill" || -L "$WS/.cursor/skills/demo:demo-skill" ]]; then
  echo "FAIL: excluded planet skill was synced"
  FAIL=$((FAIL + 1))
else
  echo "PASS: excluded planet skill pruned after sync"
  PASS=$((PASS + 1))
fi

case "$(cat "$TMP/add_missing.txt")" in
  ok) echo "PASS: exclude intercept (no Unknown option)"; PASS=$((PASS + 1)) ;;
  leaked) echo "FAIL: exclude leaked to sync-clients Unknown option"; FAIL=$((FAIL + 1)) ;;
  *) echo "FAIL: exclude add without planet should fail"; FAIL=$((FAIL + 1)) ;;
esac

# CLI write from a legacy-only workspace must migrate managed fields to v1.2.
LEGACY_WS="$TMP/legacy-ws"
mkdir -p "$LEGACY_WS/.solar" "$LEGACY_WS/sun" "$LEGACY_WS/planets"
printf '%s\n' '{"layout":"solar-client-v1.1","core_version":"old","core_source":"global","custom_user":"keep"}' \
  >"$LEGACY_WS/.solar/manifest.json"
(
  cd "$LEGACY_WS"
  export SOLAR_WORKSPACE="$LEGACY_WS"
  export SOLAR_ROOT="$ROOT"
  bash "$SYNC" exclude add solar >/dev/null
)
legacy_layout="$(python3 -c 'import json; print(json.load(open("'"$LEGACY_WS"'/.solar/settings.json"))["layout"])')"
legacy_scope="$(python3 -c 'import json; print(json.load(open("'"$LEGACY_WS"'/.solar/settings.json"))["scope"])')"
legacy_custom="$(python3 -c 'import json; print(json.load(open("'"$LEGACY_WS"'/.solar/settings.json"))["custom_user"])')"
assert_eq "legacy CLI write upgrades layout" "$legacy_layout" "solar-client-v1.2"
assert_eq "legacy CLI write forces workspace scope" "$legacy_scope" "workspace"
assert_eq "legacy CLI write preserves unknown key" "$legacy_custom" "keep"
assert_ok "legacy CLI write removes manifest" test ! -f "$LEGACY_WS/.solar/manifest.json"

# Corrupt settings must fail closed before publishing any planet resource.
INVALID_WS="$TMP/invalid-ws"
mkdir -p "$INVALID_WS/.solar" "$INVALID_WS/sun" \
  "$INVALID_WS/planets/solar/skills/probe" "$INVALID_WS/.codex/skills"
printf '%s\n' '{ invalid json' >"$INVALID_WS/.solar/settings.json"
cat >"$INVALID_WS/planets/solar/skills/probe/SKILL.md" <<'EOF'
---
name: probe
---
probe
EOF
if (
  cd "$INVALID_WS"
  export SOLAR_WORKSPACE="$INVALID_WS"
  export SOLAR_ROOT="$ROOT"
  bash "$ROOT/core/skills/solar-client/scripts/sync-clients.sh" --codex-only >/dev/null 2>&1
); then
  echo "FAIL: invalid settings should stop sync"
  FAIL=$((FAIL + 1))
else
  echo "PASS: invalid settings stop sync"
  PASS=$((PASS + 1))
fi
if [[ -e "$INVALID_WS/.codex/skills/solar:probe" || -L "$INVALID_WS/.codex/skills/solar:probe" ]]; then
  echo "FAIL: invalid settings published planet resource"
  FAIL=$((FAIL + 1))
else
  echo "PASS: invalid settings publish nothing"
  PASS=$((PASS + 1))
fi

echo
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
