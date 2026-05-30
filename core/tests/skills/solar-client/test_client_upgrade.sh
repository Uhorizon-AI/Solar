#!/usr/bin/env bash
# Unit tests for client upgrade (Fase 1.2: install prune, report).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
UPGRADE="$CORE_ROOT/skills/solar-client/scripts/client_upgrade.sh"
SOLAR="$CORE_ROOT/skills/solar-interface/scripts/solar"
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

assert_fail() {
  local label="$1"
  shift
  if "$@"; then
    echo "FAIL: $label (expected failure)" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS: $label"
    PASS=$((PASS + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

INSTALL="$TMP/install"
WS="$TMP/workspace"
mkdir -p "$INSTALL" "$WS/sun" "$WS/.solar"
cp -R "$CORE_ROOT" "$INSTALL/core"
INSTALL_SOLAR="$INSTALL/core/skills/solar-interface/scripts/solar"
echo '{"layout":"solar-client-v1.1","core_source":"global"}' > "$WS/.solar/manifest.json"
mkdir -p "$INSTALL/.cursor/skills/dummy-skill"

# shellcheck source=/dev/null
source "$INSTALL/core/skills/solar-client/scripts/client_lib.sh"

assert_ok "paths_equal same dir" solar_client_paths_equal "$TMP" "$TMP"
assert_fail "paths_equal different" solar_client_paths_equal "$INSTALL" "$WS"

artifacts="$(solar_client_list_install_artifacts "$INSTALL")"
assert_ok "lists install artifact" test -n "$artifacts"
assert_ok "artifact is .cursor" test -d "$INSTALL/.cursor/skills/dummy-skill"

pushd "$WS" >/dev/null
out_check="$(bash "$INSTALL_SOLAR" client upgrade --check 2>&1)" || true
popd >/dev/null
assert_ok "upgrade --check mentions prune" bash -c "printf '%s' \"$out_check\" | grep -q 'prune install'"
assert_ok "upgrade --check leaves dummy" test -d "$INSTALL/.cursor/skills/dummy-skill"

pushd "$WS" >/dev/null
bash "$INSTALL_SOLAR" client upgrade --skip-prune-install >/dev/null 2>&1
popd >/dev/null
assert_ok "skip-prune leaves dummy" test -d "$INSTALL/.cursor/skills/dummy-skill"

mkdir -p "$INSTALL/.cursor/skills/dummy-skill2"

pushd "$WS" >/dev/null
bash "$INSTALL_SOLAR" client upgrade >/dev/null 2>&1
popd >/dev/null
assert_ok "upgrade prunes .cursor" test ! -d "$INSTALL/.cursor"
assert_ok "upgrade keeps core/" test -f "$INSTALL/core/skills/solar-interface/scripts/solar"

LEGACY="$TMP/legacy-mono"
mkdir -p "$LEGACY/sun" "$LEGACY/planets/demo" "$LEGACY/core/skills" "$LEGACY/.github" "$LEGACY/docs"
printf '%s\n' '# workspace core' > "$LEGACY/core/AGENTS.md"
printf '%s\n' '# root agents' > "$LEGACY/AGENTS.md"
printf '%s\n' '# changelog' > "$LEGACY/CHANGELOG.md"

assert_ok "restructure needed (legacy root)" solar_client_restructure_needed "$LEGACY"

MANIFEST_LEGACY="$TMP/legacy-manifest"
cp -a "$LEGACY" "$MANIFEST_LEGACY"
mkdir -p "$MANIFEST_LEGACY/.solar"
echo '{"layout":"solar-client-v1.1"}' > "$MANIFEST_LEGACY/.solar/manifest.json"
assert_ok "restructure needed with manifest" solar_client_restructure_needed "$MANIFEST_LEGACY"

plan="$(solar_client_restructure_plan "$LEGACY")"
assert_ok "plan mkdir solar" bash -c "printf '%s' \"$plan\" | grep -q 'mkdir -p.*/solar'"
assert_ok "plan mv core" bash -c "printf '%s' \"$plan\" | grep -q 'mv.*/core.*/solar/'"
assert_ok "plan mv AGENTS.md" bash -c "printf '%s' \"$plan\" | grep -q 'mv.*/AGENTS.md.*/solar/'"
assert_ok "plan mv .github" bash -c "printf '%s' \"$plan\" | grep -q 'mv.*/.github.*/solar/'"
assert_ok "plan keeps sun" bash -c "! printf '%s' \"$plan\" | grep -Eq 'mv.*/sun(/| )'"
assert_ok "plan keeps planets" bash -c "! printf '%s' \"$plan\" | grep -Eq 'mv.*/planets(/| )'"

RESTRUCT="$TMP/restructure-apply"
cp -a "$LEGACY" "$RESTRUCT"
solar_client_restructure_apply "$RESTRUCT" false
assert_ok "apply: no core at workspace root" test ! -d "$RESTRUCT/core"
assert_ok "apply: solar has core" test -f "$RESTRUCT/solar/core/AGENTS.md"
assert_ok "apply: solar has root AGENTS.md" test -f "$RESTRUCT/solar/AGENTS.md"
assert_ok "apply: sun stays at workspace root" test -d "$RESTRUCT/sun"
assert_fail "apply: not needed after restructure" solar_client_restructure_needed "$RESTRUCT"

# Simulate client init: workspace AGENTS.md at root must not re-trigger restructure.
if [[ -f "$INSTALL/core/templates/workspace-AGENTS.md" ]]; then
  cp "$INSTALL/core/templates/workspace-AGENTS.md" "$RESTRUCT/AGENTS.md"
else
  printf '%s\n' '# Solar Workspace' > "$RESTRUCT/AGENTS.md"
fi
assert_fail "not needed after init workspace AGENTS.md at root" solar_client_restructure_needed "$RESTRUCT"

echo "---"
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
