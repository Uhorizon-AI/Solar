#!/usr/bin/env bash
# Unit tests for workspace portable bundle (Fase 3B).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SOLAR="$CORE_ROOT/skills/solar-client/scripts/solar"
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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# bundle remove runs sync-clients.sh. Keep it off the machine runtime and launchctl.
# shellcheck source=../../../../tests/support/shell_runtime_guard.sh
source "$CORE_ROOT/tests/support/shell_runtime_guard.sh"
mkdir -p "$TMP/guard-bin" "$TMP/guard-runtime"
cat >"$TMP/guard-bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/guard-bin/launchctl"
export PATH="$TMP/guard-bin:${PATH}"
export SOLAR_RUNTIME_ROOT="$TMP/guard-runtime"
export SOLAR_CLIENT_LAUNCHCTL="$TMP/guard-bin/launchctl"
solar_test_guard

INSTALL="$TMP/install"
WS="$TMP/workspace"
mkdir -p "$INSTALL" "$WS/sun/preferences" "$WS/planets" "$WS/.solar"
touch "$WS/sun/MEMORY.md" "$WS/sun/preferences/profile.md"
cp -R "$CORE_ROOT" "$INSTALL/core"
echo '{"layout":"solar-client-v1.1","core_source":"global","requires_global_client":true}' > "$WS/.solar/manifest.json"

export SOLAR_ROOT="$INSTALL"
export SOLAR_WORKSPACE="$WS"

pushd "$WS" >/dev/null
assert_ok "bundle create" bash "$SOLAR" client bundle create
assert_ok "manifest portable" grep -q workspace-snapshot .solar/settings.json
assert_ok "bundle index exists" test -f .solar/bundle/index.json
assert_ok "bundle contains solar-state" test -f .solar/bundle/core/skills/solar-state/scripts/solar_state.py
assert_ok "bundle contains the cutover script" test -f .solar/bundle/core/skills/solar-state/scripts/solar_state_cutover.py
assert_ok "every bundled skill import is in the bundle" python3 - "$INSTALL/core" "$WS/.solar/bundle" "$CORE_ROOT/skills/solar-client/scripts/client_bundle_build.py" <<'PY'
import importlib.util, sys
from pathlib import Path
core, bundle, mod_path = map(Path, sys.argv[1:4])
spec = importlib.util.spec_from_file_location("client_bundle_build", mod_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
all_skills = mod.discover_skills(core, Path("/nonexistent"))
missing = []
skills_root = bundle / "core" / "skills"
for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
    texts = []
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        texts.append(skill_md.read_text(encoding="utf-8", errors="replace"))
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        for sf in scripts.rglob("*"):
            if sf.is_file() and sf.suffix in {".sh", ".py", ".md"}:
                texts.append(sf.read_text(encoding="utf-8", errors="replace"))
    for text in texts:
        deps, _ = mod.refs_from_text(text, skill_dir, core)
        for dep in deps:
            if dep in all_skills and not (skills_root / dep).is_dir():
                missing.append(f"{skill_dir.name} -> {dep}")
if missing:
    sys.stderr.write("\n".join(missing) + "\n")
    sys.exit(1)
PY
assert_ok "bundle verify" bash "$SOLAR" client bundle verify

assert_ok "bundle create refresh (portable)" bash "$SOLAR" client bundle create
assert_ok "bundle refresh index exists" test -f .solar/bundle/index.json

doc_refresh="$(bash "$SOLAR" client doctor 2>&1 || true)"
assert_ok "doctor no secret scan noise" bash -c "! echo \"$doc_refresh\" | grep -q 'bundle secret scan'"

unset SOLAR_ROOT SOLAR_WORKSPACE
assert_ok "resolve portable without global install" bash -c "
  source \"$INSTALL/core/skills/solar-paths/scripts/resolve_solar_paths.sh\"
  solar_resolve_paths --workspace \"$WS\" --quiet
  got=\"\$(solar_core_dir)\"
  want=\"$WS/.solar/bundle/core\"
  python3 -c 'import os,sys; sys.exit(0 if os.path.realpath(sys.argv[1])==os.path.realpath(sys.argv[2]) else 1)' \"\$got\" \"\$want\"
"

assert_ok "doctor portable without global" bash "$SOLAR" client doctor
assert_ok "bundle has no legacy core/scripts runtime" bash -c "
  ! find .solar/bundle/core/scripts -maxdepth 1 -name 'sync-clients.sh' 2>/dev/null | grep -q .
"

python3 - <<PY
import json
from pathlib import Path
p = Path("$WS/.solar/settings.json")
data = json.loads(p.read_text())
data["workspace_id"] = "bundle-ws"
p.write_text(json.dumps(data) + "\n")
PY
set +e
rm_out="$(SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="" bash "$SOLAR" client bundle remove 2>&1)"
rm_ec=$?
set -e
assert_ok "bundle remove without a global install exits non-zero" test "$rm_ec" -ne 0
assert_ok "bundle remove without a global install keeps the bundle" test -f .solar/bundle/index.json
assert_ok "bundle remove without a global install keeps snapshot settings" grep -q workspace-snapshot .solar/settings.json
assert_ok "bundle remove without a global install says nothing changed" grep -q 'Nothing was changed' <<<"$rm_out"

mkdir -p .claude/skills .gemini/skills .codex/skills
ln -s "$(pwd)/.solar/bundle/core/skills/solar-client" .claude/skills/solar-client
ln -s "$(pwd)/.solar/bundle/core/skills/solar-paths" .gemini/skills/solar-paths
ln -s "$(pwd)/.solar/bundle/core/skills/solar-state" .codex/skills/solar-state
set +e
rm_ok="$(SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$INSTALL" bash "$SOLAR" client bundle remove 2>&1)"
rm_ok_ec=$?
set -e
assert_ok "bundle remove exits 0" test "$rm_ok_ec" -eq 0
assert_ok "bundle remove returns core_source global" grep -q '"core_source": "global"' .solar/settings.json
assert_ok "bundle remove drops the snapshot checksum" bash -c '! grep -q bundle_checksum .solar/settings.json'
assert_ok "bundle remove keeps workspace_id" grep -q bundle-ws .solar/settings.json
assert_ok "bundle remove moves the bundle aside" test ! -e .solar/bundle
assert_ok "bundle remove leaves the aside copy" bash -c 'compgen -G .solar/bundle.removed-* >/dev/null'
assert_ok "bundle remove leaves no dangling IDE link" python3 - "$INSTALL" <<'PY'
import os, sys
from pathlib import Path
install = os.path.realpath(sys.argv[1])
dangling = []
relinked = False
for folder in (".claude", ".gemini", ".codex"):
    root = Path(folder)
    if not root.is_dir():
        dangling.append(f"missing {folder}")
        continue
    links = [p for p in root.rglob("*") if p.is_symlink()]
    if not links:
        dangling.append(f"no links under {folder}")
        continue
    for link in links:
        raw = os.readlink(link)
        if ".solar/bundle" in raw:
            dangling.append(f"{link} still points at the bundle ({raw})")
            continue
        if not link.exists():
            dangling.append(f"{link} -> {raw}")
            continue
        if os.path.realpath(link).startswith(install + os.sep):
            relinked = True
if not relinked:
    dangling.append("no IDE link points at the global install")
if dangling:
    sys.stderr.write("\n".join(dangling) + "\n")
    sys.exit(1)
PY
[[ "$rm_ok_ec" -eq 0 ]] || echo "$rm_ok" >&2

# Settings stay workspace-snapshot. The snapshot itself is missing or not a
# valid bundle. remove must still return to global and republish IDE links.
_assert_broken_snapshot_removed() {
  local label="$1" case_ws="$2" aside="${3:-false}"
  assert_ok "$label exits 0" test "$broken_ec" -eq 0
  assert_ok "$label restores core_source global" grep -q '"core_source": "global"' "$case_ws/.solar/settings.json"
  assert_ok "$label drops the snapshot checksum" bash -c '! grep -q bundle_checksum "$1"' _ "$case_ws/.solar/settings.json"
  assert_ok "$label keeps workspace_id" grep -q "$label" "$case_ws/.solar/settings.json"
  if [[ "$aside" == true ]]; then
    assert_ok "$label moves the invalid bundle aside" test ! -e "$case_ws/.solar/bundle"
    assert_ok "$label leaves the aside copy" bash -c 'compgen -G "$1"/.solar/bundle.removed-* >/dev/null' _ "$case_ws"
  else
    assert_ok "$label does not require a bundle directory" test ! -e "$case_ws/.solar/bundle"
  fi
  assert_ok "$label does not stop on an invalid snapshot" bash -c '! grep -q "bundle is missing or invalid" <<<"$1"' _ "$broken_out"
  assert_ok "$label republishes IDE links from the global install" python3 - "$case_ws" "$INSTALL" <<'PY'
import os, sys
from pathlib import Path
ws, install = map(os.path.realpath, sys.argv[1:3])
dangling = []
relinked = False
for folder in (".claude", ".gemini", ".codex"):
    root = Path(ws) / folder
    links = [p for p in root.rglob("*") if p.is_symlink()]
    if not links:
        dangling.append(f"no links under {folder}")
        continue
    for link in links:
        raw = os.readlink(link)
        if ".solar/bundle" in raw:
            dangling.append(f"{link} still points at the bundle ({raw})")
            continue
        if not link.exists():
            dangling.append(f"{link} -> {raw}")
            continue
        if os.path.realpath(link).startswith(install + os.sep):
            relinked = True
if not relinked:
    dangling.append("no IDE link points at the global install")
if dangling:
    sys.stderr.write("\n".join(dangling) + "\n")
    sys.exit(1)
PY
  [[ "$broken_ec" -eq 0 ]] || echo "$broken_out" >&2
}

for broken_mode in missing invalid; do
  BROKEN_WS="$TMP/broken-$broken_mode"
  mkdir -p "$BROKEN_WS/sun" "$BROKEN_WS/.solar" \
    "$BROKEN_WS/.claude/skills" "$BROKEN_WS/.gemini/skills" "$BROKEN_WS/.codex/skills"
  printf '%s\n' "{\"layout\":\"solar-client-v1.2\",\"scope\":\"workspace\",\"core_source\":\"workspace-snapshot\",\"core_version\":\"v0\",\"bundle_path\":\".solar/bundle\",\"bundle_checksum\":\"gone\",\"requires_global_client\":false,\"workspace_id\":\"$broken_mode\"}" \
    >"$BROKEN_WS/.solar/settings.json"
  if [[ "$broken_mode" == "invalid" ]]; then
    mkdir -p "$BROKEN_WS/.solar/bundle/core"
    printf '%s\n' 'corrupt' >"$BROKEN_WS/.solar/bundle/core/BROKEN"
  fi
  ln -s "$BROKEN_WS/.solar/bundle/core/skills/solar-client" "$BROKEN_WS/.claude/skills/solar-client"
  ln -s "$BROKEN_WS/.solar/bundle/core/skills/solar-paths" "$BROKEN_WS/.gemini/skills/solar-paths"
  ln -s "$BROKEN_WS/.solar/bundle/core/skills/solar-state" "$BROKEN_WS/.codex/skills/solar-state"
  set +e
  broken_out="$(
    cd "$BROKEN_WS"
    unset SOLAR_ROOT SOLAR_WORKSPACE SOLAR_CORE_SOURCE SOLAR_GLOBAL_ROOT
    SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$INSTALL" bash "$SOLAR" client bundle remove 2>&1
  )"
  broken_ec=$?
  set -e
  if [[ "$broken_mode" == "invalid" ]]; then
    _assert_broken_snapshot_removed "$broken_mode" "$BROKEN_WS" true
  else
    _assert_broken_snapshot_removed "$broken_mode" "$BROKEN_WS" false
  fi
done

# SOLAR_WORKSPACE is unset and SOLAR_ROOT is the valid bundle. remove must
# skip that bundle when it looks for the global install, then leave no
# dangling IDE link.
STUCK_WS="$TMP/stuck-root"
mkdir -p "$STUCK_WS/sun" "$STUCK_WS/.solar" "$TMP/empty-home" \
  "$STUCK_WS/.claude/skills" "$STUCK_WS/.gemini/skills" "$STUCK_WS/.codex/skills"
printf '%s\n' '{"layout":"solar-client-v1.2","scope":"workspace","core_source":"global","core_version":"v0","requires_global_client":true,"workspace_id":"stuck-root"}' \
  >"$STUCK_WS/.solar/settings.json"
set +e
stuck_create="$(
  cd "$STUCK_WS"
  unset SOLAR_WORKSPACE SOLAR_GLOBAL_ROOT SOLAR_CORE_SOURCE
  SOLAR_ROOT="$INSTALL" \
  SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE="$INSTALL" \
    bash "$SOLAR" client bundle create 2>&1
)"
stuck_create_ec=$?
set -e
assert_ok "stuck-root bundle create exits 0" test "$stuck_create_ec" -eq 0
[[ "$stuck_create_ec" -eq 0 ]] || echo "$stuck_create" >&2
ln -s "$STUCK_WS/.solar/bundle/core/skills/solar-client" "$STUCK_WS/.claude/skills/solar-client"
ln -s "$STUCK_WS/.solar/bundle/core/skills/solar-paths" "$STUCK_WS/.gemini/skills/solar-paths"
ln -s "$STUCK_WS/.solar/bundle/core/skills/solar-state" "$STUCK_WS/.codex/skills/solar-state"
set +e
stuck_out="$(
  cd "$STUCK_WS"
  unset SOLAR_WORKSPACE SOLAR_GLOBAL_ROOT SOLAR_CORE_SOURCE SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE
  HOME="$TMP/empty-home" \
  SOLAR_ROOT="$STUCK_WS/.solar/bundle" \
    bash "$SOLAR" client bundle remove 2>&1
)"
stuck_ec=$?
set -e
assert_ok "stuck-root bundle remove exits 0" test "$stuck_ec" -eq 0
assert_ok "stuck-root restores core_source global" grep -q '"core_source": "global"' "$STUCK_WS/.solar/settings.json"
assert_ok "stuck-root does not treat the bundle as the global install" \
  python3 -c 'import os,sys; text=sys.argv[1]; bundle=os.path.realpath(sys.argv[2]);
line=next((ln for ln in text.splitlines() if ln.startswith("OK: core_source=global (")), "")
path=line[len("OK: core_source=global ("):-1] if line.endswith(")") else ""
raise SystemExit(0 if path and os.path.realpath(path)!=bundle else 1)' \
  "$stuck_out" "$STUCK_WS/.solar/bundle"
assert_ok "stuck-root leaves no dangling IDE link" python3 - "$STUCK_WS" <<'PY'
import os, sys
from pathlib import Path
ws = Path(sys.argv[1])
dangling = []
seen = 0
for folder in (".claude", ".gemini", ".codex"):
    root = ws / folder
    if not root.is_dir():
        continue
    for link in root.rglob("*"):
        if not link.is_symlink():
            continue
        seen += 1
        raw = os.readlink(link)
        if ".solar/bundle" in raw or not link.exists():
            dangling.append(f"{link} -> {raw}")
if seen == 0:
    dangling.append("no IDE links")
if dangling:
    sys.stderr.write("\n".join(dangling) + "\n")
    sys.exit(1)
PY
[[ "$stuck_ec" -eq 0 ]] || echo "$stuck_out" >&2

popd >/dev/null

echo ""
echo "Summary: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
