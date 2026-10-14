#!/usr/bin/env bash
# Console check. Both modes (default and --liveness) require the console to prove
# it serves THIS workspace and runtime (host_identity.py): a console that answers
# but belongs to another workspace or runtime, or reports no identity, is never
# accepted. Exit: 0 usable, 1 unavailable, 3 answering but identity not accepted.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/host_lib.sh"
solar_host_load_env
python3 - "$SOLAR_APP_BASE_URL" "${1:-}" "$SCRIPT_DIR" "$SOLAR_WORKSPACE" <<'PY'
import json,sys,time,urllib.request
from datetime import datetime
base,flag,scripts,workspace=sys.argv[1:]
code=1
identity={'state':'unreachable'}
try:
    sys.path.insert(0,scripts)
    import host_identity
    identity=host_identity.assess(base,host_identity.local_identity(workspace))
    if identity['state']!='match':
        code=3 if identity['state'] in ('mismatch','legacy','partial') else 1
        raise ValueError(identity['reason'])
    if flag == '--liveness':
        sys.exit(0)
    # The page and storage reads use the same proxy-free opener as the identity probe.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base+'/app',timeout=3) as response:
        if response.status!=200 or b'id="health"' not in response.read():
            raise ValueError('Console page unavailable')
    with opener.open(base+'/api/runtime/health',timeout=3) as response:
        data=json.load(response)
    checked=datetime.fromisoformat(data['checked_at']).timestamp()
    if data.get('service')!='solar-console' or not data.get('storage_ok') or not 0<=time.time()-checked<=120:
        raise ValueError('Storage access has not been verified recently')
    result={'available':True,'storage_ok':True,'runtime_status':data.get('status','unknown'),'base_url':base,'identity':'match'}
    if flag=='--json': print(json.dumps(result))
    elif flag!='--quiet': print('OK: Console and storage verified at '+base+'; system state: '+data['status'])
except SystemExit:
    raise
except Exception as exc:
    result={'available':False,'storage_ok':False,'runtime_status':'unknown','base_url':base,'error':str(exc),'identity':identity['state']}
    if flag=='--json': print(json.dumps(result))
    elif flag!='--quiet': print('FAIL: Console at '+base+': '+str(exc))
    sys.exit(code)
PY
