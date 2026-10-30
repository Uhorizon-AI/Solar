#!/usr/bin/env bash
# The release script must refuse to publish unless the Test suite is green on the
# commit under the release commit. gh is replaced by a double; no network.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_SH="$(cd "$SCRIPT_DIR/../../scripts" && pwd)/create-release.sh"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A repo with one commit on main and a release commit tagged on top of it.
REPO="$TMP/repo"
git init -q "$REPO"
git -C "$REPO" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m "feat: work"
git -C "$REPO" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m "chore(release): v9.9.9"
git -C "$REPO" tag v9.9.9

# gh double: prints $GH_FIXTURE for `gh api`, or fails when GH_FAIL=1.
mkdir -p "$TMP/bin"
cat >"$TMP/bin/gh" <<'STUB'
#!/usr/bin/env bash
[[ "${GH_FAIL:-0}" == 1 ]] && exit 1
[[ "$1" == api ]] && { cat "$GH_FIXTURE"; exit 0; }
exit 1
STUB
chmod +x "$TMP/bin/gh"
export PATH="$TMP/bin:$PATH"

fixture() { # ubuntu_conclusion macos_conclusion
  local macos=""
  [[ -n "$2" ]] && macos=",{\"name\":\"Suite (macos-latest)\",\"status\":\"completed\",\"conclusion\":\"$2\",\"started_at\":\"2026-10-30T10:00:00Z\"}"
  printf '{"check_runs":[{"name":"Suite (ubuntu-latest)","status":"completed","conclusion":"%s","started_at":"2026-10-30T10:00:00Z"}%s]}\n' "$1" "$macos" >"$TMP/fixture.json"
  export GH_FIXTURE="$TMP/fixture.json"
}

# Runs require_green_suite in a subshell so its `exit` does not end this test.
gate() { # urgent_reason
  local reason="${1:-}"
  (
    set --   # the sourced script parses its own arguments; give it none
    source "$RELEASE_SH"
    GIT_ROOT="$REPO"
    URGENT_REASON="$reason"
    require_green_suite v9.9.9
  ) >"$TMP/out.txt" 2>&1
}

fixture success success
gate && pass "both checks green: publish allowed" || fail "both checks green: publish allowed"

fixture success failure
gate && fail "macOS red: publish refused" || pass "macOS red: publish refused"
grep -q "Suite (macos-latest): failure" "$TMP/out.txt" && pass "the red check is named" || fail "the red check is named"

fixture failure success
gate && fail "Ubuntu red: publish refused" || pass "Ubuntu red: publish refused"

fixture success ""
gate && fail "a missing check is not green: publish refused" || pass "a missing check is not green: publish refused"

fixture success success
GH_FAIL=1 gate && fail "GitHub unreachable fails closed" || pass "GitHub unreachable fails closed"

fixture failure failure
gate "hotfix for a broken update" && pass "--urgent publishes with a red suite" || fail "--urgent publishes with a red suite"
grep -q "hotfix for a broken update" "$TMP/out.txt" && pass "--urgent prints its reason" || fail "--urgent prints its reason"

# Both publish paths, including --publish --retry, must call the gate.
for fn in publish_release retry_publish; do
  if awk "/^function $fn\\(\\)/,/^}/" "$RELEASE_SH" | grep -q 'require_green_suite'; then
    pass "$fn calls the suite gate"
  else
    fail "$fn calls the suite gate"
  fi
done

echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
