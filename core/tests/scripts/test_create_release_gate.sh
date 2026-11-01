#!/usr/bin/env bash
# Release integration, exact-commit checks and single-tag publication. No network.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_SH="$(cd "$SCRIPT_DIR/../../scripts" && pwd)/create-release.sh"
PASS=0 FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
REPO="$TMP/repo"
REMOTE="$TMP/origin.git"
git init -q --bare "$REMOTE"
git init -q -b main "$REPO"
git -C "$REPO" config user.name t
git -C "$REPO" config user.email t@example.com
mkdir -p "$REPO/core/skills/solar-client/scripts"
printf 'SOLAR_VERSION="9.9.9"\n' > "$REPO/core/skills/solar-client/scripts/solar"
chmod +x "$REPO/core/skills/solar-client/scripts/solar"
printf '## [9.9.9] - 2026-11-01\n\n### Fixed\n- Notes from the tagged commit.\n' > "$REPO/CHANGELOG.md"
printf 'fixture readme\n' > "$REPO/README.md"
git -C "$REPO" add .
git -C "$REPO" commit -qm 'feat: work'
PARENT="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" remote add origin "$REMOTE"
git -C "$REPO" push -q origin main
git -C "$REPO" commit -q --allow-empty -m 'chore(release): v9.9.9'
SHA="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" tag v9.9.9
git -C "$REPO" tag -a v8.8.8 -m unrelated "$PARENT"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALLS"
[[ "${GH_FAIL:-0}" == 1 ]] && exit 1
if [[ "${GH_RELEASE_TEST:-0}" == 1 ]]; then
  [[ "$1" == auth && "$2" == status ]] && exit 0
  [[ "$1" == release && "$2" == view ]] && exit 1
  if [[ "$1" == release && "$2" == create ]]; then
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == --notes-file ]]; then cp "$2" "$GH_NOTES"; break; fi
      shift
    done
    exit 0
  fi
fi
if [[ "$1" == api ]]; then
  if [[ -n "${GH_ONLY_SHA:-}" && "$2" != *"/commits/$GH_ONLY_SHA/"* ]]; then
    printf '{"check_runs":[]}\n'
  else
    cat "$GH_FIXTURE"
  fi
  exit 0
fi
exit 1
STUB
chmod +x "$TMP/bin/gh"
REAL_GIT="$(command -v git)"
export REAL_GIT
cat > "$TMP/bin/git" <<'STUB'
#!/usr/bin/env bash
if [[ "${GIT_FAIL_LS_REMOTE:-0}" == 1 ]]; then
  for arg in "$@"; do [[ "$arg" == ls-remote ]] && exit 1; done
fi
exec "$REAL_GIT" "$@"
STUB
cat > "$TMP/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CURL_CALLS"
for arg in "$@"; do
  if [[ "$arg" == '%{http_code}' ]]; then
    attempt=0
    if [[ -n "${CURL_ATTEMPT_FILE:-}" ]]; then
      [[ ! -f "$CURL_ATTEMPT_FILE" ]] || attempt="$(cat "$CURL_ATTEMPT_FILE")"
      attempt=$((attempt + 1))
      printf '%s' "$attempt" > "$CURL_ATTEMPT_FILE"
    fi
    if [[ -n "${CURL_RECOVER_AFTER:-}" && "$attempt" -ge "$CURL_RECOVER_AFTER" ]]; then
      printf 200
    else
      printf '%s' "${CURL_STATUS:-200}"
    fi
    exit 0
  fi
done
if [[ -n "${CURL_BODY:-}" ]]; then printf '%s\n' "$CURL_BODY"; else printf '%s\n' '{"tag_name":"v9.9.9","draft":false,"prerelease":false}'; fi
STUB
cat > "$TMP/bin/sleep" <<'STUB'
#!/usr/bin/env bash
[[ -z "${SLEEP_CALLS:-}" ]] || printf '%s\n' "$*" >> "$SLEEP_CALLS"
exit 0
STUB
chmod +x "$TMP/bin/git" "$TMP/bin/curl" "$TMP/bin/sleep"
export PATH="$TMP/bin:$PATH"
export GH_CALLS="$TMP/gh-calls"
fixture() {
  python3 - "$1" "$2" > "$TMP/fixture.json" <<'PY'
import json, sys
print(json.dumps({'check_runs': [dict(name=f'Suite ({os}-latest)', status='completed', conclusion=result, started_at='2026-11-01T10:00:00Z') for os, result in zip(('ubuntu', 'macos'), sys.argv[1:]) if result]}))
PY
  export GH_FIXTURE="$TMP/fixture.json"
}
gate() {
  local reason="${1:-}"
  (
    set --
    source "$RELEASE_SH"
    GIT_ROOT="$REPO" URGENT_REASON="$reason"
    require_green_suite "$SHA"
  ) > "$TMP/out" 2>&1
}
fixture success success
gate && pass 'both exact-commit checks green' || fail 'both exact-commit checks green'
grep -q "/commits/$SHA/check-runs" "$GH_CALLS" && pass 'queries release SHA, not parent' || fail 'queries release SHA, not parent'
GH_ONLY_SHA="$PARENT" gate && fail 'green parent cannot authorize unchecked release' || pass 'green parent cannot authorize unchecked release'
fixture success failure
gate && fail 'macOS failure refuses' || pass 'macOS failure refuses'
grep -q 'Suite (macos-latest): failure' "$TMP/out" && pass 'names failing check' || fail 'names failing check'
fixture failure success
gate && fail 'Ubuntu failure refuses' || pass 'Ubuntu failure refuses'
fixture success ''
gate && fail 'missing check refuses' || pass 'missing check refuses'
fixture success success
GH_FAIL=1 gate && fail 'API unavailable fails closed' || pass 'API unavailable fails closed'
fixture failure failure
gate 'urgent hotfix' && pass 'urgent bypasses suite only' || fail 'urgent bypasses suite only'
grep -q 'urgent hotfix' "$TMP/out" && pass 'urgent reason printed' || fail 'urgent reason printed'

# Real local git transport; mock only installer and GitHub Release side effects.
flow() {
  local mode="$1" reason="${2:-}"
  : > "$TMP/effects"
  (
    set --
    source "$RELEASE_SH"
    GIT_ROOT="$REPO" FORCE_VERSION=v9.9.9 URGENT_REASON="$reason"
    require_publisher_authority() { :; }
    run_local_install_e2e() { echo e2e >> "$TMP/effects"; [[ "${E2E_FAIL:-0}" != 1 ]] || exit 1; }
    create_github_release() { echo release >> "$TMP/effects"; }
    verify_remote_release() { echo verified >> "$TMP/effects"; }
    if [[ "$mode" == retry ]]; then retry_publish; else publish_release v9.9.9; fi
  ) > "$TMP/out" 2>&1
}
fixture success success
for mode in publish retry; do
  for reason in '' 'urgent hotfix'; do
    flow "$mode" "$reason" && fail "$mode refuses unmerged commit ($reason)" || pass "$mode refuses unmerged commit ($reason)"
    [[ ! -s "$TMP/effects" ]] && pass "$mode unmerged has no effects ($reason)" || fail "$mode unmerged has no effects ($reason)"
  done
done
[[ -z "$(git --git-dir="$REMOTE" tag -l)" ]] && pass 'failed integration gate pushes no tag' || fail 'failed integration gate pushes no tag'
# Integrate fixture only after verifying the original failure is refused.
git -C "$REPO" push -q origin main
fixture failure failure
for mode in publish retry; do
  flow "$mode" && fail "$mode refuses red exact checks" || pass "$mode refuses red exact checks"
  [[ ! -s "$TMP/effects" ]] && pass "$mode red gate has no effects" || fail "$mode red gate has no effects"
done
fixture success success
# Fail ls-remote only: fetching main and reading exact-commit checks still succeed.
for mode in publish retry; do
  GIT_FAIL_LS_REMOTE=1 flow "$mode" && fail "$mode refuses unavailable remote tag query" || pass "$mode refuses unavailable remote tag query"
  [[ ! -s "$TMP/effects" ]] && pass "$mode remote query failure has no effects" || fail "$mode remote query failure has no effects"
  grep -q 'Cannot read remote tag' "$TMP/out" && pass "$mode reached the tag query failure" || fail "$mode reached the tag query failure"
done
# A green but dirty checkout must not be used to test or publish a tag.
printf dirty > "$REPO/dirty"
flow publish && fail 'dirty checkout refuses' || pass 'dirty checkout refuses'
rm "$REPO/dirty"
E2E_FAIL=1 flow publish && fail 'installer failure refuses' || pass 'installer failure refuses'
[[ -z "$(git --git-dir="$REMOTE" tag -l)" ]] && pass 'installer failure pushes no tag' || fail 'installer failure pushes no tag'
# No pre-created tag is needed in the new prepare/merge/publish flow.
git -C "$REPO" config push.followTags true
git -C "$REPO" tag -d v9.9.9 > /dev/null
flow publish && pass 'merged checked HEAD publishes' || fail 'merged checked HEAD publishes'
[[ "$(git --git-dir="$REMOTE" tag -l)" == v9.9.9 ]] && pass 'publishes only requested tag' || fail 'publishes only requested tag'
grep -q release "$TMP/effects" && pass 'creates Release after tag' || fail 'creates Release after tag'
[[ "$(git --git-dir="$REMOTE" rev-parse main)" == "$SHA" ]] && pass 'remote main unchanged by publish' || fail 'remote main unchanged by publish'
flow retry && pass 'retry accepts matching integrated remote tag' || fail 'retry accepts matching integrated remote tag'
# Annotated tags compare their peeled commit, not the tag object.
git -C "$REPO" tag -fa v9.9.9 -m release "$SHA" > /dev/null
git -C "$REPO" push -q --force origin refs/tags/v9.9.9
flow retry && pass 'annotated remote tag identity accepted' || fail 'annotated remote tag identity accepted'
git -C "$REPO" tag -f v9.9.9 "$SHA" > /dev/null
flow publish && pass 'matching remote annotated tag needs no rewrite' || fail 'matching remote annotated tag needs no rewrite'
# Simulate a partial/mismatched remote tag; neither path may rewrite it.
git -C "$REPO" tag -f v9.9.9 "$PARENT" > /dev/null
git -C "$REPO" push -q --force origin refs/tags/v9.9.9
git -C "$REPO" tag -f v9.9.9 "$SHA" > /dev/null
for mode in publish retry; do
  flow "$mode" && fail "$mode refuses mismatched remote tag" || pass "$mode refuses mismatched remote tag"
  [[ ! -s "$TMP/effects" ]] && pass "$mode tag mismatch has no effects" || fail "$mode tag mismatch has no effects"
done
[[ "$(git --git-dir="$REMOTE" rev-parse refs/tags/v9.9.9)" == "$PARENT" ]] && pass 'existing remote tag never moved' || fail 'existing remote tag never moved'
# Local tag differing from HEAD also fails before effects.
git -C "$REPO" tag -f v9.9.9 "$PARENT" > /dev/null
flow publish && fail 'publish refuses differing local tag' || pass 'publish refuses differing local tag'
git -C "$REPO" tag -f v9.9.9 "$SHA" > /dev/null
# Public CLI recovery forwards the selected version and never runs a local writer.
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$REPO" PUBLISH=true FORCE_VERSION=v1.2.3
  python3() { printf '%s\n' "$*" > "$TMP/retry-forward"; }
  publish_release() { exit 99; }
  main
) > "$TMP/out" 2>&1 && grep -q 'retry --version v1.2.3' "$TMP/retry-forward" && pass 'explicit version is forwarded to remote recovery' || fail 'explicit version is forwarded to remote recovery'

(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$REPO"
  validate_release_version v1.2.3 "$SHA"
) > "$TMP/out" 2>&1 && fail 'version metadata mismatch refuses' || pass 'version metadata mismatch refuses'

# Preparation is local, on a new release branch, without a premature tag.
PREP="$TMP/prep"
git clone -q "$REPO" "$PREP"
git -C "$PREP" config user.name t
git -C "$PREP" config user.email t@example.com
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$PREP" NEW_VERSION=v9.9.10 LOCAL_ONLY=true
  preflight_checks() { :; }; get_last_tag() { :; }; analyze_commits() { :; }
  calculate_version() { :; }; generate_changelog() { :; }; show_preview_and_confirm() { :; }
  update_changelog() { :; }; update_readme_bootstrap_pin() { :; }
  bump_solar_cli_version() { printf 'SOLAR_VERSION="9.9.10"\n' > "$PREP/core/skills/solar-client/scripts/solar"; }
  CHANGELOG_FILE="$PREP/CHANGELOG.md" README_FILE="$PREP/README.md" SOLAR_CLI="$PREP/core/skills/solar-client/scripts/solar"
  touch "$CHANGELOG_FILE" "$README_FILE"
  prepare_release
) > "$TMP/out" 2>&1 && pass 'preparation succeeds locally' || fail 'preparation succeeds locally'
[[ "$(git -C "$PREP" branch --show-current)" == release/v9.9.10 ]] && pass 'preparation creates release branch' || fail 'preparation creates release branch'
git -C "$PREP" rev-parse --verify refs/tags/v9.9.10 > /dev/null 2>&1 && fail 'preparation creates no tag' || pass 'preparation creates no tag'
[[ "$(git -C "$PREP" log -1 --format=%s)" == 'chore(release): v9.9.10' ]] && pass 'preparation commits metadata' || fail 'preparation commits metadata'
# An existing release branch must stop preparation before any metadata mutation.
git -C "$PREP" switch -q main
BEFORE="$(git -C "$PREP" rev-parse HEAD)"
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$PREP" NEW_VERSION=v9.9.10 LOCAL_ONLY=true
  preflight_checks() { :; }; get_last_tag() { :; }; analyze_commits() { :; }
  calculate_version() { :; }; generate_changelog() { :; }; show_preview_and_confirm() { :; }
  update_changelog() { echo mutated >> "$TMP/prep-effects"; }
  bump_solar_cli_version() { echo mutated >> "$TMP/prep-effects"; }
  update_readme_bootstrap_pin() { echo mutated >> "$TMP/prep-effects"; }
  create_release_commit() { echo mutated >> "$TMP/prep-effects"; }
  prepare_release
) > "$TMP/out" 2>&1 && fail 'existing release branch refuses preparation' || pass 'existing release branch refuses preparation'
[[ ! -e "$TMP/prep-effects" && "$(git -C "$PREP" rev-parse HEAD)" == "$BEFORE" && -z "$(git -C "$PREP" status --porcelain)" ]] && pass 'branch collision preserves metadata and commit' || fail 'branch collision preserves metadata and commit'

# Retry from a different branch with dirty notes must publish the tagged notes.
git -C "$REPO" push -q --force origin refs/tags/v9.9.9
git -C "$REPO" switch -qc future-notes
printf 'Notes from a later branch.\n' > "$REPO/CHANGELOG.md"
git -C "$REPO" add CHANGELOG.md
git -C "$REPO" commit -qm 'docs: later notes'
printf 'Uncommitted notes must not be published.\n' > "$REPO/CHANGELOG.md"
: > "$GH_CALLS"
export GH_NOTES="$TMP/published-notes" CURL_CALLS="$TMP/curl-calls"
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$REPO" FORCE_VERSION=v9.9.9 RELEASE_REPO=Example/ReleaseFixture
  export GH_RELEASE_TEST=1
  require_publisher_authority() { :; }
  retry_publish
) > "$TMP/out" 2>&1 && pass 'retry accepts another branch with dirty changelog' || fail 'retry accepts another branch with dirty changelog'
grep -q 'Notes from the tagged commit.' "$GH_NOTES" && ! grep -Eq 'later branch|Uncommitted' "$GH_NOTES" && pass 'release notes match tagged commit only' || fail 'release notes match tagged commit only'
for operation in view create; do
  grep -q "release $operation v9.9.9 .*--repo Example/ReleaseFixture" "$GH_CALLS" && pass "release $operation uses configured repository" || fail "release $operation uses configured repository"
done
grep -q "repos/Example/ReleaseFixture/commits/$SHA/check-runs" "$GH_CALLS" && pass 'suite uses configured repository' || fail 'suite uses configured repository'
grep -q 'https://api.github.com/repos/Example/ReleaseFixture/releases/tags/v9.9.9' "$CURL_CALLS" && pass 'Release API uses configured repository' || fail 'Release API uses configured repository'
grep -q 'https://raw.githubusercontent.com/Example/ReleaseFixture/v9.9.9/' "$CURL_CALLS" && pass 'bootstrap URL uses configured repository' || fail 'bootstrap URL uses configured repository'
# No local tag: explain the exact non-destructive fetch needed before retry.
git -C "$REPO" tag -d v9.9.9 > /dev/null
flow retry && fail 'retry refuses absent local tag' || pass 'retry refuses absent local tag'
grep -q 'git fetch origin tag v9.9.9' "$TMP/out" && pass 'missing local tag gives explicit fetch command' || fail 'missing local tag gives explicit fetch command'

# Default submission delegates to GitHub and returns without local publication.
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$PREP"
  python3() { echo "$2" >> "$TMP/request-flow"; }
  prepare_release() { echo prepare >> "$TMP/request-flow"; NEW_VERSION=v9.9.10; }
  publish_release() { echo unexpected-publish >> "$TMP/request-flow"; exit 99; }
  main
) > "$TMP/out" 2>&1 && pass 'default command submits without manual publication' || fail 'default command submits without manual publication'
[[ "$(cat "$TMP/request-flow")" == "$(printf 'check\nprepare\nsubmit')" ]] && pass 'default command checks prepares and submits in order' || fail 'default command checks prepares and submits in order'
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$PREP" LOCAL_ONLY=true
  python3() { echo unexpected-network >> "$TMP/local-flow"; exit 99; }
  prepare_release() { echo prepare >> "$TMP/local-flow"; NEW_VERSION=v9.9.10; }
  main
) > "$TMP/out" 2>&1 && [[ "$(cat "$TMP/local-flow")" == prepare ]] && pass 'local mode prepares without submission' || fail 'local mode prepares without submission'

# Resume previews and requires explicit confirmation before any external submit.
git -C "$PREP" switch -q release/v9.9.10
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$PREP" RESUME=true
  python3() { echo "$2" >> "$TMP/resume-no-consent"; }
  main < /dev/null
) > "$TMP/out" 2>&1 && fail 'noninteractive resume requires confirmation' || pass 'noninteractive resume requires confirmation'
[[ "$(cat "$TMP/resume-no-consent")" == preview-resume ]] && pass 'unconfirmed resume never submits' || fail 'unconfirmed resume never submits'
(
  set --
  source "$RELEASE_SH"
  GIT_ROOT="$PREP" RESUME=true AUTO_CONFIRM=true
  python3() { echo "$*" >> "$TMP/resume-confirmed"; }
  main < /dev/null
) > "$TMP/out" 2>&1 && grep -q 'preview-resume --version v9.9.10 --sha' "$TMP/resume-confirmed" && grep -q 'submit --version v9.9.10 --sha' "$TMP/resume-confirmed" && pass 'confirmed resume pins preview and submit SHA' || fail 'confirmed resume pins preview and submit SHA'

cli() { bash "$RELEASE_SH" "$@" > "$TMP/cli" 2>&1; echo $?; }
[[ "$(cli --urgent hotfix)" == 2 ]] && pass 'urgent requires publish' || fail 'urgent requires publish'
[[ "$(cli --publish --urgent --yes)" == 2 ]] && pass 'urgent requires written reason' || fail 'urgent requires written reason'
[[ "$(cli --publish --urgent '   ')" == 2 ]] && pass 'urgent refuses blank reason' || fail 'urgent refuses blank reason'
[[ "$(cli --help)" == 0 ]] && grep -q 'integration or tag identity' "$TMP/cli" && pass 'help documents integration gate' || fail 'help documents integration gate'
[[ "$(cli --help)" == 0 ]] && grep -q 'local tags are not required' "$TMP/cli" && pass 'help documents remote recovery' || fail 'help documents remote recovery'
(
  set --
  source "$RELEASE_SH"
  unset SOLAR_RELEASE_INTERNAL_PUBLISH GITHUB_ACTIONS
  require_publisher_authority v9.9.9 "$SHA"
) > "$TMP/out" 2>&1 && fail 'local helper cannot write release artifacts' || pass 'local helper cannot write release artifacts'
verify_api() {
  local payload="$1"
  (
    set --
    source "$RELEASE_SH"
    export CURL_BODY="$payload"
    verify_remote_release v9.9.9
  ) > "$TMP/out" 2>&1
}
verify_api '{"tag_name":"v9.9.9","draft":true,"prerelease":false}' && fail 'draft Release is not publication success' || pass 'draft Release is not publication success'
verify_api '{"tag_name":"v9.9.9","draft":false,"prerelease":true}' && fail 'prerelease is not stable publication success' || pass 'prerelease is not stable publication success'
verify_api '{"tag_name":"v1.0.0","draft":false,"prerelease":false}' && fail 'wrong Release identity fails verification' || pass 'wrong Release identity fails verification'
CURL_STATUS=404 verify_api '{"tag_name":"v9.9.9","draft":false,"prerelease":false}' && fail 'missing public bootstrap fails verification' || pass 'missing public bootstrap fails verification'
CURL_STATUS=404 CURL_RECOVER_AFTER=2 CURL_ATTEMPT_FILE="$TMP/propagation-attempts" SLEEP_CALLS="$TMP/propagation-sleeps" verify_api '{"tag_name":"v9.9.9","draft":false,"prerelease":false}' && pass 'bootstrap propagation succeeds on second attempt' || fail 'bootstrap propagation succeeds on second attempt'
[[ "$(cat "$TMP/propagation-attempts")" == 2 && "$(wc -l < "$TMP/propagation-sleeps" | tr -d ' ')" == 1 ]] && pass 'bootstrap retry waits once using test sleep double' || fail 'bootstrap retry waits once using test sleep double'
CURL_STATUS=404 CURL_ATTEMPT_FILE="$TMP/exhausted-attempts" verify_api '{"tag_name":"v9.9.9","draft":false,"prerelease":false}' && fail 'bootstrap retry exhaustion fails' || pass 'bootstrap retry exhaustion fails'
[[ "$(cat "$TMP/exhausted-attempts")" == 5 ]] && pass 'bootstrap retry is bounded to five attempts' || fail 'bootstrap retry is bounded to five attempts'
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
