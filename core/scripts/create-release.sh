#!/usr/bin/env bash
set -euo pipefail

# Solar Release Creation Script
# Creates framework releases with semantic versioning and changelog generation
# Usage: bash core/scripts/create-release.sh [--push]

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHANGELOG_FILE="$ROOT_DIR/CHANGELOG.md"
PUSH_AFTER_RELEASE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --push)
      PUSH_AFTER_RELEASE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: bash core/scripts/create-release.sh [--push]"
      exit 2
      ;;
  esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

function error() {
  echo -e "${RED}✗ $1${NC}" >&2
}

function success() {
  echo -e "${GREEN}✓ $1${NC}"
}

function info() {
  echo -e "${BLUE}ℹ $1${NC}"
}

function warn() {
  echo -e "${YELLOW}⚠ $1${NC}"
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

function preflight_checks() {
  info "Running pre-flight checks..."

  # Check we're in git repo
  if ! git rev-parse --git-dir > /dev/null 2>&1; then
    error "Not a git repository"
    exit 2
  fi

  # Check working tree is clean
  if [[ -n $(git status --porcelain) ]]; then
    error "Working tree is not clean. Commit or stash changes first."
    git status --short
    exit 2
  fi

  # Check we're on main branch
  CURRENT_BRANCH=$(git branch --show-current)
  if [[ "$CURRENT_BRANCH" != "main" ]]; then
    error "Not on main branch (current: $CURRENT_BRANCH)"
    exit 2
  fi

  # Check CHANGELOG.md exists
  if [[ ! -f "$CHANGELOG_FILE" ]]; then
    error "CHANGELOG.md not found at $CHANGELOG_FILE"
    exit 2
  fi

  success "Pre-flight checks passed"
}

# ============================================================================
# Get Last Release Tag
# ============================================================================

function get_last_tag() {
  # Get last tag matching v*.*.* pattern
  LAST_TAG=$(git tag --list 'v*.*.*' --sort=-v:refname | head -n 1 || echo "")

  if [[ -z "$LAST_TAG" ]]; then
    warn "No previous release tag found"
    LAST_TAG="v0.0.0"
    FIRST_RELEASE=true
  else
    info "Last release: $LAST_TAG"
    FIRST_RELEASE=false
  fi
}

# ============================================================================
# Analyze Commits (Conventional Commits)
# ============================================================================

function analyze_commits() {
  info "Analyzing commits since $LAST_TAG..."

  # Get commits since last tag
  if [[ "$FIRST_RELEASE" == true ]]; then
    COMMITS=$(git log --oneline --no-merges)
  else
    COMMITS=$(git log "${LAST_TAG}..HEAD" --oneline --no-merges)
  fi

  if [[ -z "$COMMITS" ]]; then
    error "No commits since last release"
    exit 2
  fi

  # Count commit types
  BREAKING_COUNT=$(echo "$COMMITS" | grep -cE '^[a-f0-9]+ [a-z]+(\([^)]+\))?!:' || true)
  FEAT_COUNT=$(echo "$COMMITS" | grep -cE '^[a-f0-9]+ feat(\([^)]+\))?:' || true)
  FIX_COUNT=$(echo "$COMMITS" | grep -cE '^[a-f0-9]+ fix(\([^)]+\))?:' || true)

  # Check for BREAKING CHANGE in commit bodies
  if [[ "$FIRST_RELEASE" == true ]]; then
    BREAKING_BODY_COUNT=$(git log --format=%B --no-merges | grep -c "^BREAKING CHANGE:" || true)
  else
    BREAKING_BODY_COUNT=$(git log "${LAST_TAG}..HEAD" --format=%B --no-merges | grep -c "^BREAKING CHANGE:" || true)
  fi

  TOTAL_BREAKING=$((BREAKING_COUNT + BREAKING_BODY_COUNT))

  echo ""
  echo "   - $TOTAL_BREAKING BREAKING changes  → MAJOR bump"
  echo "   - $FEAT_COUNT feat commits     → MINOR bump"
  echo "   - $FIX_COUNT fix commits      → PATCH bump"
  echo ""
}

# ============================================================================
# Calculate Version Bump
# ============================================================================

function calculate_version() {
  # Parse current version (remove 'v' prefix)
  if [[ "$LAST_TAG" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
  else
    # Default to 0.0.0 if no valid tag
    MAJOR=0
    MINOR=0
    PATCH=0
  fi

  # Calculate bump based on precedence: MAJOR > MINOR > PATCH
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

# ============================================================================
# CHANGELOG helpers ([Unreleased] vs commit subjects)
# ============================================================================

# Skip release/changelog housekeeping commits when auto-generating notes.
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

# ============================================================================
# Generate CHANGELOG Entry
# ============================================================================

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

  # Get commits grouped by type
  if [[ "$FIRST_RELEASE" == true ]]; then
    FEAT_COMMITS=$(git log --oneline --no-merges --grep="^feat" || true)
    FIX_COMMITS=$(git log --oneline --no-merges --grep="^fix" || true)
    BREAKING_COMMITS=$(git log --oneline --no-merges --grep="^[a-z]+(\([^)]+\))?!:" || true)
  else
    FEAT_COMMITS=$(git log "${LAST_TAG}..HEAD" --oneline --no-merges --grep="^feat" || true)
    FIX_COMMITS=$(git log "${LAST_TAG}..HEAD" --oneline --no-merges --grep="^fix" || true)
    BREAKING_COMMITS=$(git log "${LAST_TAG}..HEAD" --oneline --no-merges --grep="^[a-z]+(\([^)]+\))?!:" || true)
  fi

  # Build changelog sections
  CHANGELOG_SECTIONS=""

  append_filtered_commits() {
    local section_header="$1"
    local commits="$2"
    local wrote_header=false
    local line msg

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

# ============================================================================
# Show Preview and Confirm
# ============================================================================

function show_preview_and_confirm() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -e "${BLUE}📌 Proposed version: $NEW_VERSION${NC}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "CHANGELOG preview:"
  echo "$CHANGELOG_ENTRY"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  # Ask for confirmation
  read -p "Do you want to create this release? [y/N]: " -n 1 -r
  echo ""

  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    warn "Release cancelled by user"
    exit 1
  fi
}

# ============================================================================
# Update CHANGELOG.md
# ============================================================================

function update_changelog() {
  info "Updating CHANGELOG.md..."

  local temp_file entry_file
  temp_file=$(mktemp)
  entry_file=$(mktemp)

  printf '%s\n' "$CHANGELOG_ENTRY" > "$entry_file"

  # Insert the new version after [Unreleased] and drop prior [Unreleased] body.
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

# ============================================================================
# Create Git Tag and Commit
# ============================================================================

function create_tag_and_commit() {
  info "Creating git tag $NEW_VERSION..."

  # Stage CHANGELOG
  git add "$CHANGELOG_FILE"

  # Create commit
  git commit -m "chore(release): $NEW_VERSION"

  # Create tag
  git tag "$NEW_VERSION"

  success "Tag $NEW_VERSION created"
}

# ============================================================================
# Push to Remote (optional)
# ============================================================================

function push_to_remote() {
  if [[ "$PUSH_AFTER_RELEASE" == true ]]; then
    info "Pushing to remote..."
    git push origin main --tags
    success "Pushed to remote"
  else
    info "Not pushing to remote (use --push flag to auto-push)"
    echo ""
    echo "To push manually:"
    echo "  git push origin main --tags"
  fi
}

# ============================================================================
# Main Execution
# ============================================================================

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
  create_tag_and_commit
  push_to_remote

  echo ""
  echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║  🎉 Release $NEW_VERSION created successfully!     ${NC}"
  echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
  echo ""

  if [[ "$PUSH_AFTER_RELEASE" == false ]]; then
    echo "Next steps:"
    echo "  1. Push to remote: git push origin main --tags"
    echo "  2. Create GitHub release (manual or via Actions)"
    echo ""
  fi
}

# Run main
main
