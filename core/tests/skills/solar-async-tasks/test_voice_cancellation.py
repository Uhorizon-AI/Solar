import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

CORE=Path(__file__).resolve().parents[3]
SCRIPTS=CORE/'skills/solar-async-tasks/scripts'
sys.path.insert(0,str(SCRIPTS))
sys.path.insert(0,str(CORE/'skills/solar-state/scripts'))
from queue_mirror import env_for, mirror, seed
from task_cancel import request
import solar_state

class CancellationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.ws=Path(self.tmp.name)
        self.root=self.ws/'sun/runtime/async-tasks'
        for name in ['queued','active','drafts','planned','completed','error','archive']:(self.root/name).mkdir(parents=True)
        self.env=env_for(self.root,{**os.environ,'SOLAR_WORKSPACE':str(self.ws),'SOLAR_ROOT':str(CORE.parent)})
    def tearDown(self): self.tmp.cleanup()
    def task(self, directory):
        p=self.root/directory/'task.md';p.write_text('---\nid: "test-cancel"\ntitle: "Cancellation test"\nstatus: '+directory+'\npriority: normal\nscheduled_time: "now"\nrecurring: false\n---\nReview fixture\n');return p
    def _pid(self):
        with solar_state.session() as store:
            row=store.task_get('test-cancel')
            return row.get('pid') if row else None
    def test_queued_cancel_never_starts(self):
        self.task('queued');seed(self.root);request(self.root,'test-cancel')
        p=subprocess.run(['bash',str(SCRIPTS/'start_next.sh')],env=self.env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        mirror(self.root)
        self.assertTrue((self.root/'cancelled/task.md').exists())
        self.assertEqual(list((self.root/'active').glob('*.md')),[])
    def test_active_cancel_acknowledges_only_after_process_stop(self):
        self.task('active');seed(self.root);router=self.ws/'router.py'
        router.write_text('import time\ntime.sleep(30)\n')
        p=subprocess.Popen([sys.executable,str(SCRIPTS/'execute_active.py'),'test-cancel',str(router)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+5
            pid=None
            while time.monotonic()<deadline:
                pid=self._pid()
                if pid: break
                time.sleep(.05)
            self.assertTrue(pid)
            request(self.root,'test-cancel')
            out,err=p.communicate(timeout=8)
            self.assertEqual(p.returncode,130,out+err)
            mirror(self.root)
            self.assertTrue((self.root/'cancelled/task.md').exists(),out+err)
            with self.assertRaises(ProcessLookupError):os.kill(int(pid),0)
        finally:
            if p.poll() is None:p.kill();p.wait()
    def test_voice_worker_overrides_unsafe_provider_tools(self):
        task=self.task('active');task.write_text(task.read_text().replace('priority: normal','origin_channel: voice\npriority: normal'))
        seed(self.root)
        router=self.ws/'router.py';router.write_text('''import json,os,sys
payload=json.load(sys.stdin)
assert payload['provider']=='claude'
cmd=os.environ['SOLAR_ROUTER_CLAUDE_CMD']
assert '--tools Read,Glob,Grep' in cmd and '--strict-mcp-config' in cmd
assert 'bypassPermissions' not in cmd
print(json.dumps({'status':'success','reply_text':'Prepared fixture','provider_used':'claude'}))
''')
        p=subprocess.run([sys.executable,str(SCRIPTS/'execute_active.py'),'test-cancel',str(router)],env=self.env,capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        log=Path(self.env['SOLAR_RUNTIME_ROOT'])/'task-logs'/'test-cancel.log'
        self.assertIn('Prepared fixture',log.read_text())

if __name__=='__main__':unittest.main()
