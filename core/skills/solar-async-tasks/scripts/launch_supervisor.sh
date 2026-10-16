#!/usr/bin/env bash
# launch_supervisor.sh — start one supervisor candidate, detached from the caller.
#
# The candidate is started with Popen(start_new_session=True), stdin null and stdout/stderr on the
# supervisor's own log, so it inherits none of the pipes of the tick (or test) that called this. It
# then competes for the runtime lock: only the winner becomes the supervisor, the others exit
# without dispatching. Two launchers at once start a single candidate. A live supervisor or
# candidate is never replaced.
#
# Usually reached through ensure_async_tasks.sh; calling it by hand is safe.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${SOLAR_WORKSPACE:-}" ]]; then
  _RESOLVE="$(cd "$SCRIPT_DIR/../../solar-paths/scripts" && pwd)/resolve_solar_paths.sh"
  if [[ -f "$_RESOLVE" ]]; then
    # shellcheck source=/dev/null
    source "$_RESOLVE"
    solar_resolve_paths --quiet 2>/dev/null || true
  fi
fi

exec python3 "$SCRIPT_DIR/supervisor_lib.py" launch
