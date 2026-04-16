#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

bash core/skills/solar-browser/scripts/onboard_browser_env.sh
bash core/skills/solar-browser/scripts/ensure_browser.sh
bash core/skills/solar-browser/scripts/check_browser.sh
