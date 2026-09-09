#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
python3 - "$SOLAR_APP_BASE_URL" "${1:-}" <<'PY'
import json,sys,time,urllib.request
from datetime import datetime
base,flag=sys.argv[1:]
try:
    if flag == '--liveness':
        with urllib.request.urlopen(base+'/health',timeout=3) as response:
            data=json.load(response)
        if response.status != 200 or not data.get('process_ok'):
            raise ValueError('Console process unavailable')
        sys.exit(0)
    with urllib.request.urlopen(base+'/app',timeout=3) as response:
        if response.status!=200 or b'id="health"' not in response.read():
            raise ValueError('Console page unavailable')
    with urllib.request.urlopen(base+'/api/runtime/health',timeout=3) as response:
        data=json.load(response)
    checked=datetime.fromisoformat(data['checked_at']).timestamp()
    if data.get('service')!='solar-console' or not data.get('storage_ok') or not 0<=time.time()-checked<=120:
        raise ValueError('Storage access has not been verified recently')
    result={'available':True,'storage_ok':True,'runtime_status':data.get('status','unknown'),'base_url':base}
    if flag=='--json': print(json.dumps(result))
    elif flag!='--quiet': print('OK: Console and storage verified at '+base+'; system state: '+data['status'])
except Exception as exc:
    result={'available':False,'storage_ok':False,'runtime_status':'unknown','base_url':base,'error':str(exc)}
    if flag=='--json': print(json.dumps(result))
    elif flag!='--quiet': print('FAIL: Console at '+base+': '+str(exc))
    sys.exit(1)
PY
