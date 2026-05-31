#!/usr/bin/env bash
# Remove stale "Python" entries from macOS System Settings → Notifications.
# Requires Full Disk Access for the terminal running this script (Cursor/Terminal).
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
APPLY=0
LIST_ONLY=0

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [--list] [--apply]

macOS keeps notification apps in two places (not git, not Solar config):
  1. usernoted SQLite (db2/db)
  2. group.com.apple.usernoted.plist (apps[] — what System Settings shows)

Old Python/uv tray runs register "Python" here even after switching to Solar.app.

  --list    Show matching rows (default if no --apply)
  --apply   Delete SQLite rows, clean plist, then restart usernoted

Requires Full Disk Access for this terminal:
  System Settings → Privacy & Security → Full Disk Access → enable Cursor or Terminal

After --apply, quit System Settings (Cmd+Q) and reopen Notifications to refresh.
Use Solar.app or terminal-notifier for new alerts (see solar-host SKILL.md).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "SKIP: macOS only"
  exit 0
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Missing: sqlite3" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing: python3" >&2
  exit 1
fi

fda_app_hint() {
  case "${TERM_PROGRAM:-}" in
    Apple_Terminal) echo "Terminal" ;;
    iTerm.app) echo "iTerm" ;;
    vscode) echo "Cursor" ;;
    *) echo "Cursor" ;;
  esac
}

open_fda_settings() {
  open "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles" 2>/dev/null \
    || open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null \
    || true
}

find_notification_db() {
  if [[ -f "$HOME/Library/Group Containers/group.com.apple.usernoted/db2/db" ]]; then
    echo "$HOME/Library/Group Containers/group.com.apple.usernoted/db2/db"
    return 0
  fi
  darwin_dir="$(getconf DARWIN_USER_DIR 2>/dev/null || true)"
  if [[ -n "$darwin_dir" && -f "${darwin_dir}com.apple.notificationcenter/db2/db" ]]; then
    echo "${darwin_dir}com.apple.notificationcenter/db2/db"
    return 0
  fi
  return 1
}

USERNOTED_PLIST="$HOME/Library/Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist"

is_python_app() {
  python3 - "$1" <<'PY'
import sys
bid = sys.argv[1].lower()
print("1" if "python" in bid or bid.startswith("org.python.") else "0")
PY
}

list_plist_python() {
  [[ -f "$USERNOTED_PLIST" ]] || return 0
  python3 - "$USERNOTED_PLIST" <<'PY'
import plistlib, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    with p.open("rb") as f:
        data = plistlib.load(f)
except OSError as e:
    print(f"  ERROR: cannot read plist: {e}", file=sys.stderr)
    sys.exit(1)
for i, app in enumerate(data.get("apps", [])):
    bid = str(app.get("bundle-id", ""))
    path = str(app.get("path", ""))
    if "python" in bid.lower() or "python" in path.lower() or bid.startswith("org.python."):
        print(f"  plist[apps[{i}]]  bundle-id={bid}")
        if path:
            print(f"    path={path}")
PY
}

clean_plist_python() {
  [[ -f "$USERNOTED_PLIST" ]] || { echo 0; return 0; }
  python3 - "$USERNOTED_PLIST" <<'PY'
import plistlib, pathlib, sys, shutil
from datetime import datetime

p = pathlib.Path(sys.argv[1])
with p.open("rb") as f:
    data = plistlib.load(f)
apps = data.get("apps", [])
filtered = []
removed = 0
for app in apps:
    bid = str(app.get("bundle-id", ""))
    path = str(app.get("path", ""))
    if "python" in bid.lower() or "python" in path.lower() or bid.startswith("org.python."):
        removed += 1
        continue
    filtered.append(app)
if removed:
    backup = p.with_suffix(f".plist.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(p, backup)
    data["apps"] = filtered
    with p.open("wb") as f:
        plistlib.dump(data, f)
print(removed)
PY
}

delete_sqlite_python() {
  local sql="DELETE FROM app WHERE lower(identifier) LIKE '%python%' OR identifier LIKE 'org.python.%'; SELECT changes();"
  local out=""
  out="$(sqlite3 "$DB" "$sql" 2>&1)" && { echo "$out"; return 0; }
  if [[ "$out" != *"readonly"* && "$out" != *"locked"* && "$out" != *"busy"* ]]; then
    echo "ERROR: SQLite delete failed: $out" >&2
    return 1
  fi
  echo "SQLite write blocked ($out) — stopping usernoted and retrying..." >&2
  killall usernoted 2>/dev/null || true
  sleep 1
  out="$(sqlite3 "$DB" "$sql" 2>&1)" && { echo "$out"; return 0; }
  echo "ERROR: SQLite delete failed after usernoted stop: $out" >&2
  return 1
}

DB="$(find_notification_db || true)"
if [[ -z "$DB" ]]; then
  echo "ERROR: notification database not found" >&2
  exit 1
fi

if ! sqlite3 "$DB" "SELECT 1;" >/dev/null 2>&1; then
  app="$(fda_app_hint)"
  open_fda_settings
  cat >&2 <<EOF
ERROR: cannot read notification database (authorization denied).

macOS blocks this file unless the app running the shell has Full Disk Access.

1. System Settings should open to Privacy → Full Disk Access.
2. Click + and add **${app}.app** (usually /Applications/${app}.app).
3. Enable the toggle for ${app}.
4. **Quit ${app} completely** (Cmd+Q) and reopen — required for TCC.
5. Retry:

   bash solar/core/skills/solar-host/scripts/host_platform/macos/clean_python_notifications.sh --list

If you run from Terminal.app instead of Cursor, add Terminal.app there.

DB: $DB
EOF
  exit 1
fi

MATCH_SQL="SELECT app_id, identifier FROM app WHERE lower(identifier) LIKE '%python%' OR identifier LIKE 'org.python.%'"

echo "DB: $DB"
echo "Plist: $USERNOTED_PLIST"
echo ""
echo "Matching notification apps (SQLite):"
db_rows="$(sqlite3 -separator $'\t' "$DB" "$MATCH_SQL" 2>/dev/null || true)"
db_count=0
if [[ -z "$db_rows" ]]; then
  echo "  (none)"
else
  while IFS=$'\t' read -r app_id identifier; do
    db_count=$((db_count + 1))
    printf '  app_id=%s  identifier=%s\n' "$app_id" "$identifier"
  done <<<"$db_rows"
fi

echo ""
echo "Matching notification apps (plist — System Settings UI):"
plist_out="$(list_plist_python 2>&1 || true)"
plist_count=0
if [[ -z "$plist_out" ]]; then
  echo "  (none)"
else
  echo "$plist_out"
  plist_count="$(grep -c 'bundle-id=' <<<"$plist_out" || true)"
fi

total=$((db_count + plist_count))
if [[ "$total" -eq 0 ]]; then
  echo ""
  echo "Nothing to remove."
  exit 0
fi

if [[ "$LIST_ONLY" -eq 1 || "$APPLY" -eq 0 ]]; then
  echo ""
  echo "Dry-run. Re-run with --apply to delete and restart usernoted."
  exit 0
fi

if pgrep -f "Solar.app/Contents/MacOS/Solar" >/dev/null 2>&1; then
  echo ""
  echo "WARN: Solar.app is running — quit it first (Cmd+Q) or Python will re-register."
  echo "      killall Solar 2>/dev/null; sleep 1"
fi

if pgrep -f "Python.*host_server.py" >/dev/null 2>&1; then
  echo ""
  echo "WARN: Solar Host (host_server.py) is running as Homebrew Python."
  echo "      macOS re-lists \"Python\" in Notifications while that process is alive."
  echo "      solar host stop   # then re-run --apply"
fi

echo ""
echo "Removing Python entries (SQLite, then plist; usernoted restart last)..."

db_deleted=0
if [[ "$db_count" -gt 0 ]]; then
  db_deleted="$(delete_sqlite_python)" || exit 1
  echo "Deleted $db_deleted SQLite row(s)."
fi

plist_deleted="$(clean_plist_python)"
echo "Removed $plist_deleted plist app(s)."

echo "Restarting usernoted to refresh System Settings..."
killall usernoted 2>/dev/null || true
sleep 1
echo ""
echo "OK: done. Quit System Settings (Cmd+Q) and reopen Notifications to refresh."
echo "If Python still appears, log out and back in once."
