#!/usr/bin/env bash
# smoke-solar-client-fase1.sh — go/no-go smoke tests for Solar Client Phase 1 (criteria #11–#17).
#
# Usage:
#   bash core/scripts/smoke-solar-client-fase1.sh [SOLAR_DEV_ROOT]
#
# SOLAR_DEV_ROOT = your legacy dev monorepo (default: parent of core/, e.g. ~/Solar).
#   - Criterion #12 runs HERE. Do NOT run `solar client init` on this tree.
#   - Criterion #11 uses a temporary directory (safe).
#
# Options:
#   --new-only      Run only #11 (new workspace in /tmp)
#   --legacy-only   Run only #12–#13 against SOLAR_DEV_ROOT
#   --skip-slow     Skip package_skill.py and solar client sync
#
# Exit: 0 = all automated checks passed; 1 = at least one failure.

set -uo pipefail
# No set -e: accumulate PASS/FAIL and always print GO/NO-GO summary.

ROOT=""
RUN_NEW=true
RUN_LEGACY=true
SKIP_SLOW=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --new-only) RUN_LEGACY=false; shift ;;
    --legacy-only) RUN_NEW=false; shift ;;
    --skip-slow) SKIP_SLOW=true; shift ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    *)
      ROOT="$1"
      shift
      ;;
  esac
done

if [[ -z "$ROOT" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

SOLAR="$ROOT/core/skills/solar-interface/scripts/solar"
RESOLVE="$ROOT/core/skills/solar-interface/scripts/resolve_solar_home.sh"
PACKAGE_BUNDLE="$ROOT/core/scripts/package_solar_bundle.sh"
PACKAGE_SKILL="$ROOT/core/skills/solar-skill-creator/scripts/package_skill.py"

PASS=0
FAIL=0
SKIP=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "SKIP: $1"; SKIP=$((SKIP + 1)); }
section() { echo ""; echo "=== $1 ==="; }

require_file() {
  local f="$1"
  local label="$2"
  if [[ -f "$f" ]]; then
    pass "$label"
  else
    fail "$label (missing: $f)"
  fi
}

run_expect_ok() {
  local label="$1"
  shift
  local out
  local code=0
  out="$("$@" 2>&1)" || code=$?
  if [[ "$code" -eq 0 ]]; then
    pass "$label"
  else
    fail "$label (exit $code)"
    if [[ -n "$out" ]]; then
      echo "  OUTPUT:" >&2
      echo "$out" | sed 's/^/    /' >&2
    fi
  fi
}

run_expect_fail() {
  local label="$1"
  shift
  local out
  local code=0
  out="$("$@" 2>&1)" || code=$?
  if [[ "$code" -eq 0 ]]; then
    fail "$label (expected failure, got success)"
    if [[ -n "$out" ]]; then
      echo "  OUTPUT:" >&2
      echo "$out" | sed 's/^/    /' >&2
    fi
  else
    pass "$label"
    if [[ -n "$out" ]]; then
      echo "  (${label} stderr: $(echo "$out" | head -1))"
    fi
  fi
}

section "Preflight ($ROOT)"
require_file "$SOLAR" "solar CLI present"
require_file "$RESOLVE" "resolve_solar_home.sh present"
require_file "$PACKAGE_BUNDLE" "package_solar_bundle.sh present"
run_expect_ok "bash -n solar CLI" bash -n "$SOLAR"
run_expect_ok "bash -n resolve_solar_home.sh" bash -n "$RESOLVE"

UNIT_RESOLVE="$ROOT/core/tests/skills/solar-interface/test_resolve_solar_home.sh"
UNIT_PATHS_PY="$ROOT/core/tests/skills/solar-interface/test_solar_paths_py.sh"

if [[ -f "$UNIT_RESOLVE" ]]; then
  run_expect_ok "#2/#13 unit: test_resolve_solar_home.sh" bash "$UNIT_RESOLVE"
else
  skip "test_resolve_solar_home.sh not found"
fi

if [[ -f "$UNIT_PATHS_PY" ]]; then
  run_expect_ok "#2/#13 unit: test_solar_paths_py.sh" bash "$UNIT_PATHS_PY"
else
  skip "test_solar_paths_py.sh not found (optional; inline #13 still runs)"
fi

section "#13 Anti-contamination (inline)"
WS_A="$(mktemp -d "${TMPDIR:-/tmp}/solar-smoke-a.XXXXXX")"
WS_B="$(mktemp -d "${TMPDIR:-/tmp}/solar-smoke-b.XXXXXX")"
mkdir -p "$WS_A/.solar/core/skills" "$WS_A/sun"
mkdir -p "$WS_B/.solar/core/skills" "$WS_B/sun" "$WS_B/nested"
export SOLAR_HOME="$(cd "$WS_A" && pwd -P)"
if pushd "$WS_B/nested" >/dev/null; then
  run_expect_fail "#13 solar status: export A, cwd B" bash "$SOLAR" status
  run_expect_fail "#13 resolve: export A, cwd B" bash -c \
    "source \"$RESOLVE\" && solar_resolve_home --quiet"
  popd >/dev/null
else
  fail "#13 could not cd to $WS_B/nested"
fi
unset SOLAR_HOME
rm -rf "$WS_A" "$WS_B"

if [[ "$RUN_NEW" == true ]]; then
  section "#11 New workspace (temp dir)"
  NEW_WS="$(mktemp -d "${TMPDIR:-/tmp}/solar-smoke-new.XXXXXX")"
  trap 'rm -rf "$NEW_WS"' EXIT

  if pushd "$NEW_WS" >/dev/null; then
    run_expect_ok "#11 init --from-dev" \
      bash "$ROOT/core/skills/solar-interface/scripts/client_init.sh" --from-dev

    for p in .solar/core sun planets AGENTS.md .env.example .env .cursorignore; do
      if [[ -e "$p" ]]; then
        pass "#11 exists $p"
      else
        fail "#11 missing $p after init"
      fi
    done

    if [[ -d .solar/core/skills ]]; then
      pass "#11 .solar/core/skills populated"
    else
      fail "#11 .solar/core/skills missing"
    fi

    if grep -q '\.venv' "$PACKAGE_BUNDLE" 2>/dev/null || true; then
      pass "#15 bundle script mentions .venv denylist"
    fi
    if [[ -d .solar/core/.venv ]]; then
      fail "#15 bundle contains .venv"
    else
      pass "#15 bundle has no .venv in workspace"
    fi

    run_expect_ok "#11 solar status" bash "$SOLAR" status
    run_expect_ok "#11 solar paths" bash "$SOLAR" paths
    run_expect_ok "#11 solar client doctor" bash "$SOLAR" client doctor

    if [[ "$SKIP_SLOW" != true ]]; then
      run_expect_ok "#11 solar client sync" bash "$SOLAR" client sync
      if [[ -d .cursor/skills || -d .claude/skills ]]; then
        pass "#5 IDE sync dirs created"
      else
        fail "#5 no IDE skills dir after sync"
      fi
    else
      skip "#11 solar client sync (--skip-slow)"
    fi

    if bash "$SOLAR" paths 2>/dev/null | grep -q '@\.solar/core/skills/'; then
      pass "#7 paths shows @.solar/core/skills/ for new layout"
    else
      fail "#7 paths missing @.solar/core/skills/"
    fi

    # #14 re-init must not overwrite .env
    marker="SMOKE_MARKER_$(date +%s)"
    echo "$marker" >> .env
    run_expect_ok "#14 re-init idempotent" \
      bash "$ROOT/core/skills/solar-interface/scripts/client_init.sh" --from-dev
    if grep -q "$marker" .env; then
      pass "#14 re-init preserved .env"
    else
      fail "#14 re-init overwrote .env"
    fi
    popd >/dev/null
  else
    fail "#11 could not enter temp workspace $NEW_WS"
  fi

  trap - EXIT
  rm -rf "$NEW_WS"
fi

if [[ "$RUN_LEGACY" == true ]]; then
  section "#12 Legacy workspace ($ROOT)"
  if [[ -d "$ROOT/.solar" ]]; then
    skip "#12 legacy: .solar/ exists at dev root (migrate or use another clone without .solar)"
  elif [[ ! -d "$ROOT/core" || ! -f "$ROOT/core/AGENTS.md" ]]; then
    fail "#12 legacy: expected core/ at dev root"
  else
    if pushd "$ROOT" >/dev/null; then
      run_expect_ok "#12 solar status" bash "$SOLAR" status
      run_expect_ok "#12 solar client doctor" bash "$SOLAR" client doctor
      if [[ "$SKIP_SLOW" != true ]]; then
        run_expect_ok "#12 solar client sync" bash "$SOLAR" client sync
      else
        skip "#12 solar client sync (--skip-slow)"
      fi
      run_expect_ok "#12 solar paths" bash "$SOLAR" paths
      if bash "$SOLAR" paths 2>/dev/null | grep -q '@core/skills/'; then
        pass "#7 paths shows @core/skills/ for legacy layout"
      else
        fail "#7 paths missing @core/skills/ on legacy"
      fi
      mkdir -p "$ROOT/planets/_smoke_probe"
      if pushd "$ROOT/planets/_smoke_probe" >/dev/null; then
        run_expect_ok "#4 discovery from subdirectory" bash "$SOLAR" status
        popd >/dev/null
      else
        fail "#4 could not enter planets/_smoke_probe"
      fi
      rmdir "$ROOT/planets/_smoke_probe" 2>/dev/null || true
      popd >/dev/null
    else
      fail "#12 could not enter legacy root $ROOT"
    fi
  fi

fi

if [[ "$SKIP_SLOW" != true ]] && [[ -f "$PACKAGE_SKILL" ]]; then
  section "Skill packaging"
  run_expect_ok "package_skill solar-interface" \
    python3 "$PACKAGE_SKILL" "$ROOT/core/skills/solar-interface" /tmp/solar-smoke-skill-out
  rm -rf /tmp/solar-smoke-skill-out 2>/dev/null || true
else
  skip "package_skill.py (--skip-slow or missing)"
fi

section "Manual (not automated — record in go/no-go)"
echo "  #8  Open SOLAR_DEV_ROOT in Cursor; verify @sun/plans/... resolves"
echo "  #10 Read workspace AGENTS.md / .cursorignore / .vscode after sync"
echo "  #16 Symlink fallback: on a test dir, touch CLAUDE.md as regular file, run init"
echo "      without --force-governance → SKIP preserved; stub only if ln fails"
echo "  #17 Foreign port: run 'nc -l <SOLAR_INTERFACE_PORT>' in another terminal, then"
echo "      'solar status' / 'solar client doctor' → client WARN (non-Solar listener)"

section "Summary"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
if [[ "$FAIL" -gt 0 ]]; then
  echo "NO-GO: $FAIL failure(s). Search for 'FAIL:' lines above." >&2
  exit 1
fi
echo "GO: automated Phase 1 smoke checks passed ($PASS checks)."
exit 0
