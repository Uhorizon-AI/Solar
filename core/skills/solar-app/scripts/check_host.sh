#!/usr/bin/env bash
# check_host.sh — console availability, storage freshness and console identity.
#
# Modes:
#   --liveness : GET /health must answer 200 with process_ok and a valid identity.
#   --json     : full check, machine readable.
#   --quiet    : full check, silent.
#   (no flag)  : full check; this is the mode the system supervisor consumes.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
EXPECTED_WORKSPACE="$(solar_host_identity_workspace)"
EXPECTED_RUNTIME="$(solar_host_identity_runtime)"
python3 - "$SOLAR_APP_BASE_URL" "${1:-}" "$EXPECTED_WORKSPACE" "$EXPECTED_RUNTIME" "$SOLAR_HOST_PID_FILE" <<'PY'
import json,os,sys,time,urllib.request
from datetime import datetime
from pathlib import Path
base,flag,expected_ws,expected_rt,pid_file=sys.argv[1:6]
canon=lambda p: str(Path(p).expanduser().resolve())

def own_console_pid():
    try:
        pid=int(Path(pid_file).read_text().strip())
    except Exception:
        return False
    try:
        os.kill(pid,0)
    except Exception:
        return False
    try:
        import subprocess
        args=subprocess.run(['ps','-p',str(pid),'-o','args='],capture_output=True,text=True).stdout
    except Exception:
        return False
    return 'host_server.py' in args

def identity(data):
    # None means "this runtime's console". Any other value is a rejection reason.
    ws=str(data.get('workspace') or '')
    rt=str(data.get('runtime') or '')
    if not ws and not rt:
        return None if own_console_pid() else 'a console without identity and without this runtime\'s pid file'
    if ws and canon(ws)!=canon(expected_ws):
        return 'another workspace ('+ws+')'
    if rt and canon(rt)!=canon(expected_rt):
        return 'another runtime ('+rt+')'
    if ws and not rt:
        return None if own_console_pid() else 'a console without runtime identity and without this runtime\'s pid file'
    return None

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
