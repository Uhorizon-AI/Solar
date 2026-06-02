#!/usr/bin/env bash
set -euo pipefail

# Solar Release Creation Script
# Creates framework releases with semantic versioning and changelog generation
#
# Usage (from framework repo or Solar workspace):
#   bash core/scripts/create-release.sh [--push] [--yes] [--version vX.Y.Z]
#
# Git root is always resolved from this script's location (…/solar/), not from cwd.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHANGELOG_FILE="$GIT_ROOT/CHANGELOG.md"
SOLAR_CLI="$GIT_ROOT/core/skills/solar-interface/scripts/solar"

PUSH_AFTER_RELEASE=false
AUTO_CONFIRM=false
FORCE_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --push)
      PUSH_AFTER_RELEASE=true
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
    -h|--help)
      sed -n '1,12p' "$0"
      echo ""
      echo "Options:"
      echo "  --push              Push main and tags after release"
      echo "  --yes, -y           Skip confirmation prompt"
      echo "  --version vX.Y.Z    Use this version (must match vMAJOR.MINOR.PATCH)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: bash core/scripts/create-release.sh [--push] [--yes] [--version vX.Y.Z]" >&2
      exit 2
      ;;
  esac
done

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
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  if [[ "$AUTO_CONFIRM" == true ]]; then
    info "Auto-confirmed (--yes)"
    return 0
  fi

  if [[ ! -t 0 ]]; then
    error "Non-interactive shell: use --yes to confirm release"
    exit 2
  fi

  read -r -p "Do you want to create this release? [y/N]: " -n 1 REPLY
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

function create_tag_and_commit() {
  info "Creating git tag $NEW_VERSION..."

  git -C "$GIT_ROOT" add "$CHANGELOG_FILE"
  [[ -f "$SOLAR_CLI" ]] && git -C "$GIT_ROOT" add "$SOLAR_CLI"
  git -C "$GIT_ROOT" commit -m "chore(release): $NEW_VERSION"
  git -C "$GIT_ROOT" tag "$NEW_VERSION"

  success "Tag $NEW_VERSION created"
}

function push_to_remote() {
  if [[ "$PUSH_AFTER_RELEASE" == true ]]; then
    info "Pushing to remote..."
    git -C "$GIT_ROOT" push origin main --tags
    success "Pushed to remote"
  else
    info "Not pushing to remote (use --push flag to auto-push)"
    echo ""
    echo "To push manually:"
    echo "  cd $GIT_ROOT && git push origin main --tags"
  fi
}

function main() {
  echo ""
  echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║         Solar Release Creation                    ║${NC}"
  echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}"
  echo ""

  preflight_checks
  get_last_tag
  analyze_commits
  calculate_version
  generate_changelog
  show_preview_and_confirm

  echo ""
  echo -e "${GREEN}✅ Creating release $NEW_VERSION...${NC}"
  echo ""

  update_changelog
  bump_solar_cli_version
  create_tag_and_commit
  push_to_remote

  echo ""
  echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║  🎉 Release $NEW_VERSION created successfully!     ${NC}"
  echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
  echo ""

  if [[ "$PUSH_AFTER_RELEASE" == false ]]; then
    echo "Next steps:"
    echo "  cd $GIT_ROOT"
    echo "  git push origin main --tags"
    echo ""
  fi
}

main
