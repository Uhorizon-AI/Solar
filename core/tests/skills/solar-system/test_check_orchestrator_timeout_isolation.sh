#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CHECK="$ROOT/core/skills/solar-system/scripts/check_orchestrator.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/workspace/.solar" "$TMP/workspace/sun/runtime/async-tasks/queued" "$TMP/home/Library/LaunchAgents" "$TMP/bin"
cat >"$TMP/workspace/.solar/settings.json" <<'EOF'
{"layout":"solar-client-v1.2","core_source":"global","requires_global_client":true}
EOF
cat >"$TMP/workspace/.env" <<'EOF'
SOLAR_SYSTEM_FEATURES=async-tasks,host
SOLAR_APP_BASE_URL=http://127.0.0.1:9000
EOF

cat >"$TMP/bin/launchctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"$TMP/bin/pgrep" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$TMP/bin/launchctl" "$TMP/bin/pgrep" "$TMP/bin/curl"

set +e
output="$(
  cd "$TMP/workspace"
  HOME="$TMP/home" \
  PATH="$TMP/bin:/usr/bin:/bin" \
  SOLAR_ROOT="$ROOT" \
  SOLAR_WORKSPACE="$TMP/workspace" \
  bash "$CHECK" 2>&1
)"
set -e

if grep -q "invalid duration" <<<"$output"; then
  printf 'FAIL: async task helpers replaced the feature timeout helper\n%s\n' "$output" >&2
  exit 1
fi

if ! grep -A2 "Feature: host" <<<"$output" | grep -q "status: HEALTHY"; then
  printf 'FAIL: host health check did not run after async task inspection\n%s\n' "$output" >&2
  exit 1
fi

echo "PASS: host timeout helper remains isolated after loading task_lib.sh"
