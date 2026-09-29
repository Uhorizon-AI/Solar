#!/usr/bin/env bash
# Stamp of one LaunchAgent pass. The console reads it; it does not write it.
# Local facts only: pid files, the local /health, and the connector's /ready.
# Never curls the public hostname.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=system_lib.sh
source "$SCRIPT_DIR/system_lib.sh"
# shellcheck source=../../solar-paths/scripts/solar_runtime_paths.sh
source "$SCRIPT_DIR/../../solar-paths/scripts/solar_runtime_paths.sh"

probe_gateway() {
  local lib="$SCRIPT_DIR/../../solar-gateway/scripts/transport_gateway_lib.sh"
  # shellcheck source=/dev/null
  source "$lib"
  transport_gateway_bind_workspace
  local run_dir ws=false http=false tunnel=false health=false connector=false
  local host port body
  pid_alive() {
    local file="$1" pid
    [[ -f "$file" ]] || return 1
    pid="$(tr -d '[:space:]' <"$file" 2>/dev/null || true)"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null
  }
  run_dir="$(gateway_run_dir)"
  pid_alive "$run_dir/ws.pid" && ws=true
  pid_alive "$run_dir/http.pid" && http=true
  pid_alive "$run_dir/cloudflared.pid" && tunnel=true
  host="${SOLAR_HTTP_HOST:-127.0.0.1}"
  port="${SOLAR_HTTP_PORT:-8787}"
  case "$host" in
    127.*|localhost|::1|[::1])
      body="$(curl -fsS --max-time 2 "http://${host}:${port}/health" 2>/dev/null || true)"
      [[ "$body" == *solar-transport-gateway* ]] && health=true
      ;;
  esac
  if gateway_cloudflared_connector_ready "$run_dir/cloudflared.log"; then
    connector=true
  fi
  printf '{"processes":{"ws":%s,"http":%s,"tunnel":%s},"local_health":%s,"connector_ready":%s}' \
    "$ws" "$http" "$tunnel" "$health" "$connector"
}

features_json='{}'
gateway_json='null'
probe=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature)
      shift
      pair="${1:?feature name=result}"
      name="${pair%%=*}"
      result="${pair#*=}"
      case "$result" in
        ok|failed|skipped|deprecated|ignored) ;;
        *) echo "ERROR: feature result must be ok, failed, skipped, deprecated or ignored." >&2; exit 1 ;;
      esac
      features_json="$(FEATURES_JSON="$features_json" NAME="$name" RESULT="$result" python3 - <<'PY'
import json, os
data = json.loads(os.environ["FEATURES_JSON"])
data[os.environ["NAME"]] = os.environ["RESULT"]
print(json.dumps(data, separators=(",", ":")))
PY
)"
      ;;
    --gateway-json)
      shift
      gateway_json="${1:?gateway json}"
      probe=0
      ;;
    --probe-gateway)
      probe=1
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$probe" -eq 1 && "$gateway_json" == "null" ]]; then
  gateway_json="$(probe_gateway)"
fi

dest="$(solar_runtime_dir system --create)/pass-stamp.json"
FEATURES_JSON="$features_json" GATEWAY_JSON="$gateway_json" DEST="$dest" python3 - <<'PY'
import json, os, tempfile
from datetime import datetime, timezone
dest = os.environ["DEST"]
payload = {
    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "features": json.loads(os.environ["FEATURES_JSON"]),
    "gateway": json.loads(os.environ["GATEWAY_JSON"]),
}
folder = os.path.dirname(dest)
fd, tmp = tempfile.mkstemp(prefix=".pass-stamp.", dir=folder)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, dest)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PY
