#!/usr/bin/env bash
# check_host.sh — console availability, storage freshness and console identity.
#
# Modes:
#   --liveness : GET /health must answer 200 with process_ok and a valid identity.
#   --json     : full check, machine readable.
#   --quiet    : full check, silent.
#   (no flag)  : full check; this is the mode the system supervisor consumes.
#
# Identity (host_identity.py, the single policy): /health must report this
# runtime's workspace and runtime. A console that reports no identity, or only
# half of it, is adopted only when this runtime can prove the process is its own
# (its own pid file, or this install's host_server.py in the listener command).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
EXPECTED_WORKSPACE="$(solar_host_identity_workspace)"
EXPECTED_RUNTIME="$(solar_host_identity_runtime)"
LISTENER_COMMAND="$(ps -p "$(solar_host_port_listener_pids | head -n1 || true)" -o command= 2>/dev/null || true)"
INSTALL_ROOTS=()
while IFS= read -r _root; do
  [[ -n "$_root" ]] && INSTALL_ROOTS+=("$_root")
done < <(solar_host_identity_install_roots)
python3 - "$SCRIPT_DIR" "$SOLAR_APP_BASE_URL" "${1:-}" "$EXPECTED_WORKSPACE" "$EXPECTED_RUNTIME" \
  "$SOLAR_HOST_PID_FILE" "$LISTENER_COMMAND" ${INSTALL_ROOTS[@]+"${INSTALL_ROOTS[@]}"} <<'PY'
import json,sys,time,urllib.request
from datetime import datetime
script_dir,base,flag,expected_ws,expected_rt,pid_file,listener_command=sys.argv[1:8]
install_roots=sys.argv[8:]
sys.path.insert(0,script_dir)
import host_identity

def identity(health):
    reason=host_identity.evaluate(health=health,workspace=expected_ws,runtime=expected_rt,
                                  pid_file=pid_file,listener_command=listener_command,
                                  install_roots=install_roots)
    return None if reason is None else reason

result={'available':False,'storage_ok':False,'runtime_status':'unknown','base_url':base,
        'workspace':expected_ws,'runtime':expected_rt}
try:
    if flag == '--liveness':
        with urllib.request.urlopen(base+'/health',timeout=3) as response:
            data=json.load(response)
        if response.status != 200 or not data.get('process_ok'):
            raise ValueError('Console process unavailable')
        reason=identity(data)
        if reason:
            raise ValueError('console identity mismatch: '+reason)
        sys.exit(0)
    with urllib.request.urlopen(base+'/app',timeout=3) as response:
        if response.status!=200 or b'id="health"' not in response.read():
            raise ValueError('Console page unavailable')
    with urllib.request.urlopen(base+'/api/runtime/health',timeout=3) as response:
        data=json.load(response)
    checked=datetime.fromisoformat(data['checked_at']).timestamp()
    if data.get('service')!='solar-console' or not data.get('storage_ok') or not 0<=time.time()-checked<=120:
        raise ValueError('Storage access has not been verified recently')
    with urllib.request.urlopen(base+'/health',timeout=3) as response:
        health=json.load(response)
    reason=identity(health)
    if reason:
        raise ValueError('console identity mismatch: '+reason)
    result.update(available=True,storage_ok=True,runtime_status=data.get('status','unknown'),
                  workspace=str(health.get('workspace') or expected_ws),
                  runtime=str(health.get('runtime') or expected_rt))
    if flag=='--json': print(json.dumps(result))
    elif flag!='--quiet': print('OK: Console and storage verified at '+base+'; system state: '+data['status'])
except Exception as exc:
    result['error']=str(exc)
    if flag=='--json': print(json.dumps(result))
    elif flag!='--quiet':
        print('FAIL: Console at '+base+': '+str(exc))
        if str(exc).startswith('console identity mismatch'):
            print('  expected workspace: '+expected_ws)
            print('  expected runtime:   '+expected_rt)
    sys.exit(1)
PY
