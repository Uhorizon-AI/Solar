#!/usr/bin/env bash
set -euo pipefail

# Solar Release Creation Script
# Creates framework releases with semantic versioning and changelog generation
#
# Usage (from framework repo or Solar workspace):
#   bash core/scripts/create-release.sh [--yes] [--version vX.Y.Z]  # submit release request
#   bash core/scripts/create-release.sh --local [--version vX.Y.Z]   # local preparation only
#   bash core/scripts/create-release.sh --resume                    # resume submission
#   bash core/scripts/create-release.sh --publish [--version vX.Y.Z] # publish (A2 formal)
#   bash core/scripts/create-release.sh --publish --retry [--version vX.Y.Z]
#
# Git root is always resolved from this script's location (…/solar/), not from cwd.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHANGELOG_FILE="$GIT_ROOT/CHANGELOG.md"
README_FILE="$GIT_ROOT/README.md"
SOLAR_CLI="$GIT_ROOT/core/skills/solar-client/scripts/solar"
INSTALL_E2E_TEST="$GIT_ROOT/core/tests/skills/solar-client/test_install_solar_client.sh"
BOOTSTRAP_REL_PATH="core/skills/solar-client/scripts/bootstrap_solar_client.sh"

RELEASE_REPO="${SOLAR_RELEASE_REPO:-Uhorizon-AI/Solar}"
# The checks the Test suite workflow reports. Both must be green on the commit
# being released before anything is published.
REQUIRED_SUITE_CHECKS=("Suite (ubuntu-latest)" "Suite (macos-latest)")

PUBLISH=false
LOCAL_ONLY=false
RESUME=false
RETRY=false
AUTO_CONFIRM=false
FORCE_VERSION=""
URGENT_REASON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)
      LOCAL_ONLY=true
      shift
      ;;
    --resume)
      RESUME=true
      shift
      ;;
    --publish)
      PUBLISH=true
      shift
      ;;
    --retry)
      RETRY=true
      shift
      ;;
    --push)
      # Deprecated alias: push without Release is no longer allowed.
      PUBLISH=true
      shift
      ;;
    --yes|-y)
      AUTO_CONFIRM=true
      shift
      ;;
    --version)
      shift
      [[ $# -gt 0 ]] || { echo "ERROR: --version requires vX.Y.Z" >&2; exit 2; }
      FORCE_VERSION="$1"
      shift
      ;;
    --urgent)
      shift
      # The reason is a sentence, never another option: "--urgent --yes" must not skip the gate.
      if [[ $# -eq 0 || -z "${1//[[:space:]]/}" || "$1" == -* ]]; then
        echo "ERROR: --urgent requires a written reason (not empty, not starting with -)" >&2
        exit 2
      fi
      URGENT_REASON="$1"
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage:
  bash core/scripts/create-release.sh [--yes] [--version vX.Y.Z]
  bash core/scripts/create-release.sh --publish [--version vX.Y.Z]
  bash core/scripts/create-release.sh --publish --retry [--version vX.Y.Z]

Modes:
  (default)   Prepare, push release branch, open PR and request protected native auto-merge.
              GitHub tests the integrated commit and publishes it; no second command.
  --local     Prepare only, with no remote writes (no tag).
  --resume    Re-submit the current prepared release branch after an interrupted request.
  --publish   After PR merge: integration + exact-commit suite gate → local E2E → push one tag → Release
  --publish --retry
              Idempotent recovery when the tag is already remote but the GitHub Release is missing
              If the local tag is absent, first: git fetch origin tag vX.Y.Z

Options:
  --yes, -y           Confirm the displayed preparation/request effects without prompting
  --version vX.Y.Z    Force version (must match vMAJOR.MINOR.PATCH)
  --urgent "reason"   Only together with --publish: `--publish --urgent "reason"` publishes
                      without a green test suite. For an urgent fix only; the reason is
                      printed and stays in the terminal log. Without --publish it exits 2.
  --push              Deprecated alias for --publish

Release policy:
  Releases are grouped: one release per week (cadence proposed by the maintainer),
  covering every PR merged since the last one. An urgent fix (breaks users, security)
  may be released outside the cadence. Publishing requires the Test suite checks
  "Suite (ubuntu-latest)" and "Suite (macos-latest)" to be green on the exact
  release commit, already integrated into origin/main. --urgent skips only the suite
  gate, never integration or tag identity. See CONTRIBUTING.md.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: bash core/scripts/create-release.sh [--yes] [--version vX.Y.Z] [--publish] [--retry]" >&2
      exit 2
      ;;
  esac
done

if [[ "$LOCAL_ONLY" == true && ( "$PUBLISH" == true || "$RESUME" == true ) ]] || [[ "$RESUME" == true && "$PUBLISH" == true ]]; then
  echo "ERROR: --local, --resume and --publish are separate modes" >&2
  exit 2
fi

if [[ -n "$URGENT_REASON" && "$PUBLISH" != true ]]; then
  echo "ERROR: --urgent requires --publish" >&2
  exit 2
fi

if [[ "$RETRY" == true && "$PUBLISH" != true ]]; then
  echo "ERROR: --retry requires --publish" >&2
  exit 2
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

error() { echo -e "${RED}✗ $1${NC}" >&2; }
success() { echo -e "${GREEN}✓ $1${NC}"; }
info() { echo -e "${BLUE}ℹ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

FIRST_RELEASE=false
LAST_TAG=""
COMMITS=""
BUMP_TYPE=""
CHANGELOG_SOURCE="commits"
CHANGELOG_ENTRY=""
NEW_VERSION=""
MAJOR=0
MINOR=0
PATCH=0
FEAT_COUNT=0
FIX_COUNT=0
TOTAL_BREAKING=0

bootstrap_pin_url() {
  local tag="$1"
  printf 'https://raw.githubusercontent.com/%s/%s/%s\n' "$RELEASE_REPO" "$tag" "$BOOTSTRAP_REL_PATH"
}

function update_readme_bootstrap_pin() {
  local tag="$1"
  local url
  url="$(bootstrap_pin_url "$tag")"
  info "Pinning README Quickstart bootstrap to $tag..."

  if [[ ! -f "$README_FILE" ]]; then
    error "README.md not found: $README_FILE"
    exit 2
  fi

  if ! grep -q '<!-- solar-bootstrap-pin -->' "$README_FILE"; then
    error "README.md missing <!-- solar-bootstrap-pin --> marker"
    exit 2
  fi

  python3 - <<'PY' "$README_FILE" "$url"
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
url = sys.argv[2]
text = path.read_text(encoding="utf-8")
block = (
    "<!-- solar-bootstrap-pin -->\n"
    "```bash\n"
    f"curl -fsSL {url} | bash\n"
    "```\n"
    "<!-- /solar-bootstrap-pin -->"
)
pattern = re.compile(
    r"<!-- solar-bootstrap-pin -->.*?<!-- /solar-bootstrap-pin -->",
    re.S,
)
new_text, n = pattern.subn(block, text, count=1)
if n != 1:
    raise SystemExit("failed to update solar-bootstrap-pin block in README.md")
path.write_text(new_text, encoding="utf-8")
PY
  success "README Quickstart pin → $url"
}

function preflight_checks() {
  info "Framework repo: $GIT_ROOT"
  info "Running pre-flight checks..."

  if ! git -C "$GIT_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    error "Not a git repository: $GIT_ROOT"
    error "Run from the Solar framework checkout (directory solar/ with .git)."
    exit 2
  fi

  if [[ -n $(git -C "$GIT_ROOT" status --porcelain) ]]; then
    error "Working tree is not clean. Commit or stash changes first."
    git -C "$GIT_ROOT" status --short
    exit 2
  fi

  CURRENT_BRANCH=$(git -C "$GIT_ROOT" branch --show-current)
  if [[ "$CURRENT_BRANCH" != "main" ]]; then
    error "Not on main branch (current: $CURRENT_BRANCH)"
    exit 2
  fi

  if [[ ! -f "$CHANGELOG_FILE" ]]; then
    error "CHANGELOG.md not found at $CHANGELOG_FILE"
    exit 2
  fi

  success "Pre-flight checks passed"
}

function get_last_tag() {
  LAST_TAG=$(git -C "$GIT_ROOT" tag --list 'v*.*.*' --sort=-v:refname | head -n 1 || echo "")

  if [[ -z "$LAST_TAG" ]]; then
    warn "No previous release tag found"
    LAST_TAG="v0.0.0"
    FIRST_RELEASE=true
  else
    info "Last release: $LAST_TAG"
    FIRST_RELEASE=false
  fi
}

function is_meta_changelog_commit() {
  local subject="$1"
  [[ "$subject" =~ ^chore\(release\): ]] && return 0
  [[ "$subject" =~ ^chore\(changelog\): ]] && return 0
  [[ "$subject" =~ ^feat\(changelog\): ]] && return 0
  [[ "$subject" =~ ^docs\(changelog\): ]] && return 0
  return 1
}

function extract_unreleased_body() {
  awk '
    /^## \[Unreleased\]/ { in_unreleased=1; next }
    in_unreleased && /^## \[/ { exit }
    in_unreleased { print }
  ' "$CHANGELOG_FILE"
}

function unreleased_has_content() {
  local body
  body="$(extract_unreleased_body)"
  [[ -n "${body//[[:space:]]/}" ]]
}

function unreleased_suggests_minor() {
  local body
  body="$(extract_unreleased_body)"
  echo "$body" | grep -qE '^- feat(\(|:)|^[[:space:]]*- feat(\(|:)' || \
    echo "$body" | grep -qE '^### Added'
}

function analyze_commits() {
  info "Analyzing commits since $LAST_TAG..."

  if [[ "$FIRST_RELEASE" == true ]]; then
    COMMITS=$(git -C "$GIT_ROOT" log --oneline --no-merges)
  else
    COMMITS=$(git -C "$GIT_ROOT" log "${LAST_TAG}..HEAD" --oneline --no-merges 2>/dev/null || true)
  fi

  if [[ -z "$COMMITS" ]]; then
    if unreleased_has_content; then
      warn "No commits since $LAST_TAG — will release curated [Unreleased] only"
      COMMITS=""
    else
      error "No commits since $LAST_TAG and [Unreleased] is empty"
      exit 2
    fi
  fi

  if [[ -n "$COMMITS" ]]; then
    BREAKING_COUNT=$(echo "$COMMITS" | grep -cE '^[a-f0-9]+ [a-z]+(\([^)]+\))?!:' || true)
    FEAT_COUNT=$(echo "$COMMITS" | grep -cE '^[a-f0-9]+ feat(\([^)]+\))?:' || true)
    FIX_COUNT=$(echo "$COMMITS" | grep -cE '^[a-f0-9]+ fix(\([^)]+\))?:' || true)

    if [[ "$FIRST_RELEASE" == true ]]; then
      BREAKING_BODY_COUNT=$(git -C "$GIT_ROOT" log --format=%B --no-merges | grep -c "^BREAKING CHANGE:" || true)
    else
      BREAKING_BODY_COUNT=$(git -C "$GIT_ROOT" log "${LAST_TAG}..HEAD" --format=%B --no-merges | grep -c "^BREAKING CHANGE:" || true)
    fi
    TOTAL_BREAKING=$((BREAKING_COUNT + BREAKING_BODY_COUNT))
  else
    FEAT_COUNT=0
    FIX_COUNT=0
    TOTAL_BREAKING=0
  fi

  # Curated [Unreleased] with feat/Added lines → treat as MINOR when commits omit feat:
  if [[ $FEAT_COUNT -eq 0 ]] && unreleased_has_content && unreleased_suggests_minor; then
    FEAT_COUNT=1
    info "Bumping MINOR from [Unreleased] Added/feat entries (commit subjects may use change/fix only)"
  fi

  echo ""
  echo "   - $TOTAL_BREAKING BREAKING changes  → MAJOR bump"
  echo "   - $FEAT_COUNT feat (or [Unreleased]) → MINOR bump"
  echo "   - $FIX_COUNT fix commits             → PATCH bump"
  echo ""
}

function calculate_version() {
  if [[ -n "$FORCE_VERSION" ]]; then
    if [[ ! "$FORCE_VERSION" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
      error "Invalid --version (expected vMAJOR.MINOR.PATCH): $FORCE_VERSION"
      exit 2
    fi
    NEW_VERSION="$FORCE_VERSION"
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
    BUMP_TYPE="manual"
    info "Using forced version: $NEW_VERSION"
    return 0
  fi

  if [[ "$LAST_TAG" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
  else
    MAJOR=0
    MINOR=0
    PATCH=0
  fi

  if [[ $TOTAL_BREAKING -gt 0 ]]; then
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    BUMP_TYPE="MAJOR"
  elif [[ $FEAT_COUNT -gt 0 ]]; then
    MINOR=$((MINOR + 1))
    PATCH=0
    BUMP_TYPE="MINOR"
  else
    PATCH=$((PATCH + 1))
    BUMP_TYPE="PATCH"
  fi

  NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
  info "Proposed version: $NEW_VERSION ($BUMP_TYPE bump)"
}

function generate_changelog() {
  local today
  today=$(date +%Y-%m-%d)
  CHANGELOG_ENTRY="## [${MAJOR}.${MINOR}.${PATCH}] - $today"
  CHANGELOG_SOURCE="commits"

  if unreleased_has_content; then
    info "Using curated [Unreleased] content (skipping commit-subject generation)"
    CHANGELOG_SOURCE="unreleased"
    CHANGELOG_ENTRY+=$'\n'"$(extract_unreleased_body)"
    return 0
  fi

  warn "No curated [Unreleased] content — generating release notes from conventional commits"
  warn "Tip: maintain [Unreleased] in CHANGELOG.md before running this script for richer notes."

  local FEAT_COMMITS FIX_COMMITS BREAKING_COMMITS
  if [[ "$FIRST_RELEASE" == true ]]; then
    FEAT_COMMITS=$(git -C "$GIT_ROOT" log --oneline --no-merges --grep="^feat" || true)
    FIX_COMMITS=$(git -C "$GIT_ROOT" log --oneline --no-merges --grep="^fix" || true)
    BREAKING_COMMITS=$(git -C "$GIT_ROOT" log --oneline --no-merges --grep="^[a-z]+(\([^)]+\))?!:" || true)
  else
    FEAT_COMMITS=$(git -C "$GIT_ROOT" log "${LAST_TAG}..HEAD" --oneline --no-merges --grep="^feat" || true)
    FIX_COMMITS=$(git -C "$GIT_ROOT" log "${LAST_TAG}..HEAD" --oneline --no-merges --grep="^fix" || true)
    BREAKING_COMMITS=$(git -C "$GIT_ROOT" log "${LAST_TAG}..HEAD" --oneline --no-merges --grep="^[a-z]+(\([^)]+\))?!:" || true)
  fi

  local CHANGELOG_SECTIONS=""
  local section_header commits line msg wrote_header

  append_filtered_commits() {
    section_header="$1"
    commits="$2"
    wrote_header=false
    [[ -z "$commits" ]] && return 0
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      msg=$(echo "$line" | sed -E 's/^[a-f0-9]+ //')
      if is_meta_changelog_commit "$msg"; then
        continue
      fi
      if [[ "$wrote_header" == false ]]; then
        CHANGELOG_SECTIONS+=$'\n'"$section_header"$'\n'
        wrote_header=true
      fi
      CHANGELOG_SECTIONS+="- $msg"$'\n'
    done <<< "$commits"
  }

  append_filtered_commits "### Breaking Changes" "$BREAKING_COMMITS"
  append_filtered_commits "### Added" "$FEAT_COMMITS"
  append_filtered_commits "### Fixed" "$FIX_COMMITS"

  CHANGELOG_ENTRY+="$CHANGELOG_SECTIONS"
}

function show_preview_and_confirm() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -e "${BLUE}📌 Proposed version: $NEW_VERSION${NC} ($BUMP_TYPE)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "CHANGELOG preview:"
  echo "$CHANGELOG_ENTRY"
  echo ""
  if [[ "$LOCAL_ONLY" != true ]]; then
    echo "This requests preparation, branch push, a release PR, protected auto-merge and CI publication of $NEW_VERSION."
    echo "Required checks/reviews must pass. GitHub continues after this command exits."
  fi
  echo "Quickstart bootstrap pin:"
  echo "  $(bootstrap_pin_url "$NEW_VERSION")"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  if [[ "$AUTO_CONFIRM" == true ]]; then
    info "Release request/preparation effects confirmed (--yes)"
    return 0
  fi

  if [[ ! -t 0 ]]; then
    error "Non-interactive shell: use --yes to confirm release"
    exit 2
  fi

  read -r -p "Confirm the displayed release effects? [y/N]: " -n 1 REPLY
  echo ""

  if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    warn "Release cancelled by user"
    exit 1
  fi
}

function bump_solar_cli_version() {
  local ver="${NEW_VERSION#v}"
  if [[ ! -f "$SOLAR_CLI" ]]; then
    warn "solar CLI not found at $SOLAR_CLI — skip SOLAR_VERSION bump"
    return 0
  fi
  if ! grep -q '^SOLAR_VERSION="' "$SOLAR_CLI"; then
    warn "SOLAR_VERSION line not found in $SOLAR_CLI — skip bump"
    return 0
  fi
  info "Bumping SOLAR_VERSION in solar CLI to $ver..."
  local tmp
  tmp=$(mktemp)
  sed "s/^SOLAR_VERSION=\".*\"/SOLAR_VERSION=\"$ver\"/" "$SOLAR_CLI" > "$tmp"
  mv "$tmp" "$SOLAR_CLI"
  # sed/mv replaces the file and drops the executable bit — restore it for git + installs.
  chmod +x "$SOLAR_CLI"
  success "SOLAR_VERSION=$ver"
}

function update_changelog() {
  info "Updating CHANGELOG.md..."

  local temp_file entry_file
  temp_file=$(mktemp)
  entry_file=$(mktemp)

  printf '%s\n' "$CHANGELOG_ENTRY" > "$entry_file"

  awk -v entry_file="$entry_file" '
    BEGIN { inserted=0; in_unreleased=0 }
    /^## \[Unreleased\]/ {
      print
      print ""
      if (!inserted) {
        while ((getline line < entry_file) > 0) {
          print line
        }
        close(entry_file)
        print ""
        inserted=1
      }
      in_unreleased=1
      next
    }
    in_unreleased && /^## \[/ {
      in_unreleased=0
    }
    in_unreleased { next }
    { print }
  ' "$CHANGELOG_FILE" > "$temp_file"

  mv "$temp_file" "$CHANGELOG_FILE"
  rm -f "$entry_file"

  success "CHANGELOG.md updated"
}

function create_release_commit() {
  info "Creating release commit $NEW_VERSION (no tag until publication)..."

  git -C "$GIT_ROOT" add "$CHANGELOG_FILE" "$README_FILE" "$GIT_ROOT/.github/solar-release.json"
  if [[ -f "$SOLAR_CLI" ]]; then
    git -C "$GIT_ROOT" add "$SOLAR_CLI"
    git -C "$GIT_ROOT" update-index --chmod=+x -- "core/skills/solar-client/scripts/solar"
  fi
  git -C "$GIT_ROOT" commit -m "chore(release): $NEW_VERSION"
  success "Release commit prepared on release/$NEW_VERSION"
}

function run_local_install_e2e() {
  info "Running local install E2E before publish..."
  if [[ ! -f "$INSTALL_E2E_TEST" ]]; then
    error "E2E test missing: $INSTALL_E2E_TEST"
    exit 2
  fi
  # Drop maintainer SOLAR_WORKSPACE/SOLAR_ROOT so the fixture workspace is used.
  if ! env -u SOLAR_WORKSPACE -u SOLAR_ROOT bash "$INSTALL_E2E_TEST"; then
    error "Local install E2E failed — aborting publish (no git push)"
    exit 1
  fi
  success "Local install E2E passed"
}

# Empty result means the tag is absent. Annotated tags resolve to their commit.
function remote_tag_commit() {
  local tag="$1" refs
  refs="$(git -C "$GIT_ROOT" ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")" || return 1
  printf '%s\n' "$refs" | awk '
    $2 ~ /\^\{\}$/ { peeled=$1 }
    $2 !~ /\^\{\}$/ { direct=$1 }
    END { print (peeled != "" ? peeled : direct) }
  '
}

function verify_remote_tag() {
  local tag="$1" expected="$2" remote
  remote="$(remote_tag_commit "$tag")" || { error "Cannot read remote tag $tag"; exit 1; }
  if [[ "$remote" != "$expected" ]]; then
    error "Remote tag $tag is missing or points to a different commit; refusing to publish"
    exit 1
  fi
  success "Remote tag $tag matches $expected"
}

function require_integrated_commit() {
  local sha="$1"
  # Fetch only main; never move local branches or rewrite an existing release tag.
  git -C "$GIT_ROOT" fetch --no-tags origin '+refs/heads/main:refs/remotes/origin/main' || {
    error "Cannot refresh origin/main; refusing to publish"; exit 1;
  }
  if ! git -C "$GIT_ROOT" merge-base --is-ancestor "$sha" refs/remotes/origin/main; then
    error "Release commit $sha must be on origin/main before publication"
    echo "Push the release branch, open a PR into main, merge it, then publish the integrated commit." >&2
    echo "Existing tags are never moved automatically; inspect any partially published release first." >&2
    exit 1
  fi
}

function validate_release_version() {
  local tag="$1" sha="$2" version
  if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    error "Invalid --version (expected vMAJOR.MINOR.PATCH): $tag"; exit 2
  fi
  version="$(git -C "$GIT_ROOT" show "$sha:core/skills/solar-client/scripts/solar" |
    sed -n 's/^SOLAR_VERSION="\([^"]*\)"/\1/p')"
  if [[ "$version" != "${tag#v}" ]]; then
    error "$tag does not match SOLAR_VERSION at $sha ($version); prepare release metadata through a PR first"
    exit 1
  fi
}

function create_github_release() {
  local tag="$1" sha="$2"
  if ! command -v gh >/dev/null 2>&1; then
    error "gh is required for --publish"
    echo "Retry after installing/auth: bash core/scripts/create-release.sh --publish --retry --version $tag" >&2
    exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    error "gh is not authenticated"
    echo "Retry: bash core/scripts/create-release.sh --publish --retry --version $tag" >&2
    exit 1
  fi

  if gh release view "$tag" --repo "$RELEASE_REPO" >/dev/null 2>&1; then
    info "GitHub Release $tag already exists — skipping create"
    return 0
  fi

  local notes_file
  notes_file="$(mktemp)"
  if ! python3 - "$GIT_ROOT" "$sha" "$tag" "$notes_file" <<'PYNOTES'
import pathlib, re, subprocess, sys
repo, sha, tag, out = sys.argv[1:]
text = subprocess.run(
    ["git", "-C", repo, "show", f"{sha}:CHANGELOG.md"],
    check=True, capture_output=True, text=True, encoding="utf-8",
).stdout
ver = tag.lstrip("v")
m = re.search(rf"^## \[{re.escape(ver)}\].*?(?=^## |\Z)", text, re.M | re.S)
body = m.group(0).strip() if m else f"Solar {tag}"
pathlib.Path(out).write_text(body + "\n", encoding="utf-8")
PYNOTES
  then
    rm -f "$notes_file"
    error "Cannot read release notes from commit $sha; refusing to create the Release"
    exit 1
  fi

  if ! gh release create "$tag" --verify-tag --repo "$RELEASE_REPO" --title "$tag" --notes-file "$notes_file"; then
    rm -f "$notes_file"
    error "gh release create failed for $tag"
    echo "Retry (does not recreate commit/tag): bash core/scripts/create-release.sh --publish --retry --version $tag" >&2
    exit 1
  fi
  rm -f "$notes_file"
  success "GitHub Release $tag created"
}

function verify_remote_release() {
  local tag="$1"
  local api="https://api.github.com/repos/${RELEASE_REPO}/releases/tags/${tag}"
  local body
  if ! body="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api")"; then
    error "Release $tag not visible via API"
    echo "Retry: bash core/scripts/create-release.sh --publish --retry --version $tag" >&2
    exit 1
  fi
  local url
  url="$(bootstrap_pin_url "$tag")"
  local code
  code="$(curl -fsSL -o /dev/null -w '%{http_code}' "$url" || true)"
  if [[ "$code" != "200" ]]; then
    warn "Bootstrap raw URL returned HTTP $code (tag may not be fetched yet): $url"
  else
    success "Bootstrap raw URL OK ($url)"
  fi
  success "Release $tag verified via API"
}

# Both required checks must belong to the exact commit being released.
# The urgent exception skips only this gate, never integration or tag identity.
function require_green_suite() {
  local sha="$1"
  if [[ -n "$URGENT_REASON" ]]; then
    warn "Publishing WITHOUT the suite gate (--urgent): $URGENT_REASON"
    return 0
  fi
  info "Checking the Test suite on ${sha:0:12} (the exact release commit)..."
  if ! command -v gh >/dev/null 2>&1; then
    error "gh is required to verify the Test suite; refusing to publish"
    exit 1
  fi
  local json
  if ! json="$(gh api "repos/${RELEASE_REPO}/commits/${sha}/check-runs?per_page=100" 2>/dev/null)"; then
    error "Could not read the Test suite checks for ${sha:0:12}; refusing to publish"
    exit 1
  fi
  local problems
  problems="$(python3 - "$json" "${REQUIRED_SUITE_CHECKS[@]}" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
runs = {}
for run in data.get("check_runs", []):
    # A re-run replaces an earlier result; the latest completed one wins.
    prev = runs.get(run["name"])
    if prev is None or (run.get("started_at") or "") >= (prev.get("started_at") or ""):
        runs[run["name"]] = run
for name in sys.argv[2:]:
    run = runs.get(name)
    if run is None:
        print(f"{name}: no result")
    elif run.get("conclusion") != "success":
        print(f"{name}: {run.get('conclusion') or run.get('status')}")
PY
)" || { error "Could not read the Test suite result; refusing to publish"; exit 1; }
  if [[ -n "$problems" ]]; then
    error "The Test suite is not green on ${sha:0:12}; refusing to publish"
    echo "$problems" >&2
    echo "The exact release commit must be on origin/main and its Test suite run must have finished." >&2
    echo "Wait for it, or for an urgent fix pass: --publish --urgent \"reason\"" >&2
    exit 1
  fi
  success "Test suite green on ${sha:0:12}"
}

function publish_release() {
  local tag="$1" sha remote
  if [[ -n $(git -C "$GIT_ROOT" status --porcelain) ]]; then
    error "Working tree is not clean; refusing to publish"; exit 2
  fi
  sha="$(git -C "$GIT_ROOT" rev-parse HEAD)"
  validate_release_version "$tag" "$sha"
  if git -C "$GIT_ROOT" show-ref --verify --quiet "refs/tags/$tag"; then
    if [[ "$(git -C "$GIT_ROOT" rev-parse "refs/tags/$tag^{commit}")" != "$sha" ]]; then
      error "Local tag $tag points to a different commit; refusing to move it"; exit 1
    fi
  fi
  require_integrated_commit "$sha"
  require_green_suite "$sha"
  remote="$(remote_tag_commit "$tag")" || { error "Cannot read remote tag $tag"; exit 1; }
  if [[ -n "$remote" && "$remote" != "$sha" ]]; then
    error "Remote tag $tag points to a different commit; refusing to move it"; exit 1
  fi
  run_local_install_e2e
  if ! git -C "$GIT_ROOT" show-ref --verify --quiet "refs/tags/$tag"; then
    git -C "$GIT_ROOT" tag "$tag" "$sha"
  fi
  if [[ -z "$remote" ]]; then
    info "Pushing only $tag to origin (main is never pushed)..."
    git -C "$GIT_ROOT" push --no-follow-tags origin "refs/tags/$tag:refs/tags/$tag"
  else
    info "Remote tag $tag already matches the release commit; skipping push"
  fi
  verify_remote_tag "$tag" "$sha"
  create_github_release "$tag" "$sha"
  verify_remote_release "$tag"
}

function retry_publish() {
  local tag="${FORCE_VERSION:-}" sha
  if [[ -z "$tag" ]]; then
    tag="$(git -C "$GIT_ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)"
  fi
  if [[ -z "$tag" ]]; then
    error "Cannot determine tag for --retry; pass --version vX.Y.Z"; exit 2
  fi
  NEW_VERSION="$tag"
  if ! sha="$(git -C "$GIT_ROOT" rev-parse --verify "refs/tags/$tag^{commit}" 2>/dev/null)"; then
    error "Local tag $tag is missing; first run: git fetch origin tag $tag"; exit 1
  fi
  validate_release_version "$tag" "$sha"
  info "Retry publish for $tag (no commit/tag rewrite)"
  require_integrated_commit "$sha"
  require_green_suite "$sha"
  verify_remote_tag "$tag" "$sha"
  create_github_release "$tag" "$sha"
  verify_remote_release "$tag"
}

function prepare_release() {
  preflight_checks
  get_last_tag
  analyze_commits
  calculate_version
  if [[ "$LOCAL_ONLY" != true ]]; then
    (cd "$GIT_ROOT" && python3 "$SCRIPT_DIR/release_automation.py" check-version --version "$NEW_VERSION")
  fi
  generate_changelog
  show_preview_and_confirm

  echo ""
  echo -e "${GREEN}✅ Preparing release $NEW_VERSION...${NC}"
  echo ""

  git -C "$GIT_ROOT" switch -c "release/$NEW_VERSION" || {
    error "Cannot create release/$NEW_VERSION; release files were not modified"; exit 1;
  }
  update_changelog
  bump_solar_cli_version
  update_readme_bootstrap_pin "$NEW_VERSION"
  (cd "$GIT_ROOT" && python3 "$SCRIPT_DIR/release_automation.py" write-intent --version "$NEW_VERSION")
  create_release_commit
}

function main() {
  echo ""
  echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║         Solar Release Creation                    ║${NC}"
  echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}"
  echo ""

  if [[ "$RESUME" == true ]]; then
    NEW_VERSION="$(git -C "$GIT_ROOT" branch --show-current)"
    NEW_VERSION="${NEW_VERSION#release/}"
    if [[ -n "$FORCE_VERSION" && "$FORCE_VERSION" != "$NEW_VERSION" ]]; then
      error "--resume version does not match the current release branch"; exit 2
    fi
    (cd "$GIT_ROOT" && python3 "$SCRIPT_DIR/release_automation.py" submit --version "$NEW_VERSION")
    return 0
  fi

  if [[ "$RETRY" == true ]]; then
    retry_publish
    return 0
  fi

  if [[ "$PUBLISH" == true ]]; then
    NEW_VERSION="$FORCE_VERSION"
    if [[ -z "$NEW_VERSION" ]]; then
      NEW_VERSION="$(git -C "$GIT_ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)"
    fi
    if [[ -z "$NEW_VERSION" ]]; then
      error "Publication requires --version vX.Y.Z after the release PR is merged; it never prepares a new commit"
      exit 2
    fi
  else
    if [[ "$LOCAL_ONLY" != true ]]; then
      (cd "$GIT_ROOT" && python3 "$SCRIPT_DIR/release_automation.py" check)
    fi
    prepare_release
    if [[ "$LOCAL_ONLY" != true ]]; then
      (cd "$GIT_ROOT" && python3 "$SCRIPT_DIR/release_automation.py" submit --version "$NEW_VERSION")
      return 0
    fi
  fi

  if [[ "$PUBLISH" == true ]]; then
    publish_release "$NEW_VERSION"
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  🎉 Release $NEW_VERSION published successfully!   ${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
    echo ""
  else
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  🎉 Release $NEW_VERSION prepared locally          ${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "To request protected auto-merge and CI publication (requires explicit authority):"
    echo "  bash core/scripts/create-release.sh --resume"
    echo "Manual --publish remains available only for deliberate recovery after integration."
    echo ""
  fi
}

# Run only when executed; tests source this file to exercise single functions.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi
